"""
web_app.py - Flask Web UI for JobsDB Agent
启动方式: python web_app.py
访问: http://127.0.0.1:5000
"""
import os
import json
import uuid
import queue
import threading
import atexit
import time
import yaml

from flask import Flask, request, jsonify, Response, send_from_directory

import config
from config import (
    llm_call, set_emit_target, get_session_files, get_system_prompt,
    OUTPUT_DIR, get_current_run_dir, get_latest_run_dir,
)
from tools_defs import tools, execute_tool, deduplicate_tool_calls
from scraper import cleanup_playwright
from pdf_renderer import cleanup_renderer
from job_search import search_jobs
from job_match import match_jobs
from resume_gen import generate_resume
from market_analysis import analyze_market, batch_analyze_market


# ============================================================
#  Flask App
# ============================================================

app = Flask(__name__, static_folder="static")

# ── Session 管理 ──
_sessions = {}       # sid → {messages, queue, busy, last_done}
_sessions_lock = threading.Lock()

# ── 全局 Agent 锁（Playwright 不支持并发） ──
_agent_lock = threading.Lock()


def _get_or_create_session(sid):
    with _sessions_lock:
        if sid not in _sessions:
            _sessions[sid] = {
                "messages": [{"role": "system", "content": get_system_prompt()}],
                "queue": queue.Queue(),
                "busy": False,
            }
        return _sessions[sid]


# ============================================================
#  Agent 执行线程
# ============================================================

def _run_agent_turn(sid, user_message):
    """在后台线程中执行一轮 Agent 对话"""
    session = _get_or_create_session(sid)
    q = session["queue"]

    try:
        set_emit_target(q)

        session["messages"].append({"role": "user", "content": user_message})

        reply = llm_call(session["messages"], tools=tools)
        session["messages"].append(reply)

        # 工具调用循环
        while reply.tool_calls:
            q.put({"type": "status", "text": "Agent 正在工作..."})

            unique_calls = deduplicate_tool_calls(reply.tool_calls)

            for tc in unique_calls:
                q.put({
                    "type": "tool_call",
                    "tool": tc.function.name,
                    "args": tc.function.arguments or "{}",
                })
                result = execute_tool(tc)
                session["messages"].append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                })

            skipped = [tc for tc in reply.tool_calls if tc not in unique_calls]
            for tc in skipped:
                session["messages"].append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": "(重复调用已跳过)",
                })

            reply = llm_call(session["messages"], tools=tools)
            session["messages"].append(reply)

        # 获取本轮生成的文件
        files = get_session_files()

        done_event = {
            "type": "done",
            "reply": reply.content or "",
            "files": [[fp, desc] for fp, desc in files],
        }
        q.put(done_event)

    except Exception as e:
        q.put({"type": "error", "text": str(e)})

    finally:
        set_emit_target(None)
        session["busy"] = False
        _agent_lock.release()


# ============================================================
#  Pipeline 直接执行（不经过 LLM）
# ============================================================

def _run_pipeline(sid, action, sort_by=None, languages=None):
    """直接执行 search_jobs + match_jobs 流水线，不经过 LLM 决策。"""
    session = _get_or_create_session(sid)
    q = session["queue"]

    try:
        set_emit_target(q)

        if action == "search_match":
            q.put({"type": "status", "text": "Starting job search..."})
            search_result = search_jobs(sort_by=sort_by)
            q.put({"type": "progress", "text": search_result})

            if not search_result.startswith("❌"):
                q.put({"type": "status", "text": "Starting match analysis..."})
                match_result = match_jobs()
                q.put({"type": "progress", "text": match_result})

                if not match_result.startswith("错误"):
                    q.put({"type": "status", "text": "Generating direction-based resumes..."})
                    resume_result = generate_resume(by_direction=True, output_langs=languages)
                    q.put({"type": "progress", "text": resume_result})
                    reply = resume_result
                else:
                    reply = match_result
            else:
                reply = search_result

        else:
            reply = f"Unknown pipeline action: {action}"

        files = get_session_files()
        q.put({
            "type": "done",
            "reply": reply,
            "files": [[fp, desc] for fp, desc in files],
        })

    except Exception as e:
        q.put({"type": "error", "text": str(e)})

    finally:
        set_emit_target(None)
        session["busy"] = False
        _agent_lock.release()


# ============================================================
#  Routes
# ============================================================

@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@app.route("/api/session", methods=["POST"])
def create_session():
    sid = str(uuid.uuid4())[:8]
    _get_or_create_session(sid)
    return jsonify({"sid": sid})


@app.route("/api/pipeline", methods=["POST"])
def pipeline():
    """直接执行流水线，不经过 LLM。"""
    data = request.get_json()
    sid = data.get("sid", "")
    action = data.get("action", "")
    sort_by = data.get("sort_by")  # optional: "date" or "relevance"
    languages = data.get("languages")  # optional: ["en","hk","cn"] subset

    if not sid or not action:
        return jsonify({"error": "Missing sid or action"}), 400

    session = _get_or_create_session(sid)

    if session["busy"]:
        return jsonify({"error": "Agent is busy"}), 429

    if not _agent_lock.acquire(blocking=False):
        return jsonify({"error": "Another session is running"}), 429

    session["busy"] = True

    while not session["queue"].empty():
        try:
            session["queue"].get_nowait()
        except queue.Empty:
            break

    t = threading.Thread(
        target=_run_pipeline,
        args=(sid, action),
        kwargs={"sort_by": sort_by, "languages": languages},
        daemon=True,
    )
    t.start()

    return jsonify({"status": "started"})



@app.route("/api/chat", methods=["POST"])
def chat():
    data = request.get_json()
    sid = data.get("sid", "")
    message = data.get("message", "").strip()

    if not sid or not message:
        return jsonify({"error": "Missing sid or message"}), 400

    session = _get_or_create_session(sid)

    if session["busy"]:
        return jsonify({"error": "Agent is busy"}), 429

    if not _agent_lock.acquire(blocking=False):
        return jsonify({"error": "Another session is running"}), 429

    session["busy"] = True

    # 清空旧的 queue 事件
    while not session["queue"].empty():
        try:
            session["queue"].get_nowait()
        except queue.Empty:
            break

    t = threading.Thread(
        target=_run_agent_turn,
        args=(sid, message),
        daemon=True,
    )
    t.start()

    return jsonify({"status": "started"})


@app.route("/stream/<sid>")
def stream(sid):
    session = _get_or_create_session(sid)
    q = session["queue"]

    def generate():
        last_ping = time.time()
        idle_rounds = 0
        while True:
            try:
                event = q.get(timeout=2)
                idle_rounds = 0  # got an event, reset idle counter
                ev_type = event.get("type", "message")
                yield f"event: {ev_type}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
                if event.get("type") in ("done", "error"):
                    break
            except queue.Empty:
                # Give pipeline a few seconds to start before closing
                if not session["busy"]:
                    idle_rounds += 1
                    if idle_rounds > 4:  # ~8 seconds grace period
                        break
                # Send ping every 30s to keep connection alive
                if time.time() - last_ping > 30:
                    yield f"event: ping\ndata: {json.dumps({})}\n\n"
                    last_ping = time.time()

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.route("/api/runs")
def list_runs():
    """列出所有 run 目录及元数据"""
    runs = []
    if os.path.exists(OUTPUT_DIR):
        for d in sorted(os.listdir(OUTPUT_DIR), reverse=True):
            run_path = os.path.join(OUTPUT_DIR, d)
            if d.startswith("run_") and os.path.isdir(run_path):
                meta = {"id": d, "path": d}
                # 解析时间
                try:
                    ts = d.replace("run_", "")
                    from datetime import datetime as _dt
                    meta["time"] = _dt.strptime(ts, "%Y%m%d_%H%M%S").strftime("%Y-%m-%d %H:%M")
                except Exception:
                    meta["time"] = d

                # 检查有哪些文件 → 判断阶段
                has_raw = os.path.exists(os.path.join(run_path, "raw_jobs.json"))
                has_matched = os.path.exists(os.path.join(run_path, "matched_jobs.json"))
                has_resumes = os.path.exists(os.path.join(run_path, "resumes"))

                meta["has_raw"] = has_raw
                meta["has_matched"] = has_matched
                meta["has_resumes"] = has_resumes

                if has_matched:
                    meta["stage"] = "matched"
                elif has_raw:
                    meta["stage"] = "searched"
                else:
                    meta["stage"] = "empty"

                # 岗位计数
                if has_raw:
                    try:
                        with open(os.path.join(run_path, "raw_jobs.json"), "r", encoding="utf-8") as f:
                            meta["job_count"] = len(json.load(f))
                    except Exception:
                        meta["job_count"] = 0
                if has_matched:
                    try:
                        with open(os.path.join(run_path, "matched_jobs.json"), "r", encoding="utf-8") as f:
                            meta["match_count"] = len(json.load(f))
                    except Exception:
                        meta["match_count"] = 0

                # 标记当前活跃 run
                cur = get_current_run_dir()
                meta["is_current"] = (cur is not None and os.path.abspath(run_path) == os.path.abspath(cur))

                runs.append(meta)
    return jsonify(runs)


@app.route("/api/runs/<run_id>/files")
def run_files(run_id):
    """列出指定 run 的所有文件"""
    run_path = os.path.join(OUTPUT_DIR, run_id)
    if not os.path.isdir(run_path) or not run_id.startswith("run_"):
        return jsonify({"error": "Run not found"}), 404
    files = []
    for root, dirs, fnames in os.walk(run_path):
        for fname in fnames:
            full = os.path.join(root, fname)
            rel = os.path.relpath(full, OUTPUT_DIR).replace("\\", "/")
            size = os.path.getsize(full)
            files.append({
                "name": fname,
                "path": rel,
                "size": size,
                "mtime": os.path.getmtime(full),
            })
    files.sort(key=lambda x: x["mtime"], reverse=True)
    return jsonify(files)


@app.route("/api/files")
def list_files():
    """列出 output 目录的所有文件"""
    output_dir = "output"
    files = []
    if os.path.exists(output_dir):
        for root, dirs, fnames in os.walk(output_dir):
            for fname in fnames:
                full = os.path.join(root, fname)
                rel = os.path.relpath(full, output_dir).replace("\\", "/")
                size = os.path.getsize(full)
                files.append({
                    "name": fname,
                    "path": rel,
                    "size": size,
                    "mtime": os.path.getmtime(full),
                })
    files.sort(key=lambda x: x["mtime"], reverse=True)
    return jsonify(files)


@app.route("/api/market/files")
def market_files():
    """列出 output/market/ 下所有文件"""
    market_dir = os.path.join(OUTPUT_DIR, "market")
    files = []
    if os.path.exists(market_dir):
        for fname in os.listdir(market_dir):
            full = os.path.join(market_dir, fname)
            if os.path.isfile(full):
                files.append({
                    "name": fname,
                    "path": f"market/{fname}",
                    "size": os.path.getsize(full),
                    "mtime": os.path.getmtime(full),
                })
    files.sort(key=lambda x: x["mtime"], reverse=True)
    return jsonify(files)


# ── 匹配结果 API ──

@app.route("/api/runs/<run_id>/matches")
def run_matches(run_id):
    """返回指定 run 的结构化匹配评分数据。"""
    run_path = os.path.join(OUTPUT_DIR, run_id)
    if not os.path.isdir(run_path) or not run_id.startswith("run_"):
        return jsonify({"error": "Run not found"}), 404
    matched_path = os.path.join(run_path, "matched_jobs.json")
    if not os.path.exists(matched_path):
        return jsonify({"error": "该 Run 还没有匹配结果"}), 404
    with open(matched_path, "r", encoding="utf-8") as f:
        return jsonify(json.load(f))


# ── 简历生成 API ──

@app.route("/api/resume", methods=["POST"])
def api_resume():
    """直接调用简历生成。参数由前端表单提供，SSE 流返回进度。"""
    data = request.json or {}
    sid = data.get("sid", "").strip()
    mode = data.get("mode", "general")
    languages = data.get("languages")  # optional: ["en","hk","cn"] subset
    if not sid:
        return jsonify({"error": "Missing sid"}), 400

    session = _get_or_create_session(sid)
    if session["busy"]:
        return jsonify({"error": "Agent is busy"}), 429
    if not _agent_lock.acquire(blocking=False):
        return jsonify({"error": "Another session is running"}), 429
    session["busy"] = True

    # Clear old queue
    q = session["queue"]
    while not q.empty():
        try: q.get_nowait()
        except queue.Empty: break

    def _run():
        try:
            set_emit_target(q)
            if mode == "direction":
                result = generate_resume(by_direction=True, output_langs=languages)
            elif mode == "job":
                idx = data.get("job_index", 1)
                result = generate_resume(job_index=int(idx), output_langs=languages)
            elif mode == "jd":
                jd = data.get("jd_text", "").strip()
                if not jd:
                    q.put({"type": "error", "text": "JD 文本不能为空"})
                    return
                result = generate_resume(jd_text=jd, output_langs=languages)
            elif mode == "role":
                role = data.get("role_direction", "").strip()
                if not role:
                    q.put({"type": "error", "text": "岗位方向不能为空"})
                    return
                result = generate_resume(role_direction=role, output_langs=languages)
            else:
                result = generate_resume(output_langs=languages)

            files = get_session_files()
            q.put({"type": "done", "reply": result, "files": [[fp, desc] for fp, desc in files]})
        except Exception as e:
            q.put({"type": "error", "text": str(e)})
        finally:
            set_emit_target(None)
            session["busy"] = False
            _agent_lock.release()

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"status": "started"})


# ── 市场调研 API ──

@app.route("/api/market", methods=["POST"])
def api_market():
    """直接调用市场调研。SSE 流返回进度。"""
    data = request.json or {}
    sid = data.get("sid", "").strip()
    cat = data.get("job_category", "").strip()
    if not sid or not cat:
        return jsonify({"error": "Missing sid or job_category"}), 400

    session = _get_or_create_session(sid)
    if session["busy"]:
        return jsonify({"error": "Agent is busy"}), 429
    if not _agent_lock.acquire(blocking=False):
        return jsonify({"error": "Another session is running"}), 429
    session["busy"] = True

    q = session["queue"]
    while not q.empty():
        try: q.get_nowait()
        except queue.Empty: break

    loc = data.get("location", "Hong Kong")
    gap = data.get("include_gap_analysis", True)
    classification = data.get("classification", "")
    sort_by = data.get("sort_by") or None

    def _run():
        try:
            set_emit_target(q)
            result = analyze_market(job_category=cat, location=loc,
                                    include_gap_analysis=gap,
                                    classification=classification,
                                    sort_by=sort_by)
            files = get_session_files()
            q.put({"type": "done", "reply": result, "files": [[fp, desc] for fp, desc in files]})
        except Exception as e:
            q.put({"type": "error", "text": str(e)})
        finally:
            set_emit_target(None)
            session["busy"] = False
            _agent_lock.release()

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"status": "started"})


@app.route("/api/market/batch", methods=["POST"])
def api_market_batch():
    """批量市场调研。SSE 流返回进度。"""
    data = request.json or {}
    sid = data.get("sid", "").strip()
    tasks = data.get("tasks", [])
    if not sid or not tasks:
        return jsonify({"error": "Missing sid or tasks"}), 400

    session = _get_or_create_session(sid)
    if session["busy"]:
        return jsonify({"error": "Agent is busy"}), 429
    if not _agent_lock.acquire(blocking=False):
        return jsonify({"error": "Another session is running"}), 429
    session["busy"] = True

    q = session["queue"]
    while not q.empty():
        try: q.get_nowait()
        except queue.Empty: break

    loc = data.get("location", "Hong Kong")
    gap = data.get("include_gap_analysis", True)
    sort_by = data.get("sort_by") or None

    def _run():
        try:
            set_emit_target(q)
            result = batch_analyze_market(tasks=tasks, location=loc,
                                          include_gap_analysis=gap,
                                          sort_by=sort_by)
            files = get_session_files()
            q.put({"type": "done", "reply": result, "files": [[fp, desc] for fp, desc in files]})
        except Exception as e:
            q.put({"type": "error", "text": str(e)})
        finally:
            set_emit_target(None)
            session["busy"] = False
            _agent_lock.release()

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"status": "started"})


# ── YAML 配置读写 API ──

@app.route("/api/config/yaml/<name>", methods=["GET"])
def get_yaml_config(name):
    """读取 profiles/{name}.yaml，返回 JSON 格式内容。"""
    if name not in ("me", "search_config"):
        return jsonify({"error": "仅支持 me 或 search_config"}), 400
    data, err = config.load_yaml(f"{name}.yaml")
    if err:
        return jsonify({"error": err}), 404
    return jsonify({"name": name, "content": data})


@app.route("/api/config/yaml/<name>", methods=["PUT"])
def put_yaml_config(name):
    """回写 profiles/{name}.yaml，前端提交 JSON，后端转 YAML 存储。"""
    if name not in ("me", "search_config"):
        return jsonify({"error": "仅支持 me 或 search_config"}), 400
    data = request.json
    if not data or "content" not in data:
        return jsonify({"error": "Missing content"}), 400

    new_content = data["content"]
    # 基本校验：确保是合法 dict
    if not isinstance(new_content, dict):
        return jsonify({"error": "content 必须是 JSON 对象"}), 400

    try:
        yaml_text = yaml.dump(new_content, allow_unicode=True, default_flow_style=False)
    except Exception as e:
        return jsonify({"error": f"YAML 序列化失败: {str(e)}"}), 400

    filepath = os.path.join(config.PROFILES_DIR, f"{name}.yaml")
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(yaml_text)
        return jsonify({"status": "ok", "name": name})
    except Exception as e:
        return jsonify({"error": f"写入文件失败: {str(e)}"}), 500


# ── 模型配置 API ──

@app.route("/api/config/model", methods=["GET"])
def get_model_config():
    return jsonify(config.get_model_info())


@app.route("/api/config/model", methods=["POST"])
def set_model_config():
    data = request.json or {}
    provider = data.get("provider", "").strip()
    model = data.get("model", "").strip() or None
    if not provider:
        return jsonify({"error": "provider 不能为空"}), 400
    result = config.switch_model(provider, model)
    if "error" in result:
        return jsonify(result), 400
    return jsonify(result)


@app.route("/download/<path:filepath>")
def download(filepath):
    return send_from_directory("output", filepath, as_attachment=True)


# ============================================================
#  Cleanup
# ============================================================

atexit.register(cleanup_playwright)
atexit.register(cleanup_renderer)


# ============================================================
#  Main
# ============================================================

if __name__ == "__main__":
    print("=" * 50)
    print("  JobsDB Agent Web UI")
    print("  http://127.0.0.1:5000")
    print("=" * 50)
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)
