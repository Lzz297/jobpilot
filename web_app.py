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

from flask import Flask, request, jsonify, Response, send_from_directory

import config
from config import (
    client, set_emit_target, get_session_files, get_system_prompt,
    OUTPUT_DIR, get_current_run_dir, get_latest_run_dir,
)
from tools_defs import tools, execute_tool, deduplicate_tool_calls
from scraper import cleanup_playwright
from pdf_renderer import cleanup_renderer
from job_search import search_jobs
from job_match import match_jobs
from resume_gen import generate_resume


# ============================================================
#  Flask App
# ============================================================

app = Flask(__name__, static_folder="static")

# ── Session 管理 ──
_sessions = {}       # sid → {messages, queue, busy, last_done}
_sessions_lock = threading.Lock()

# ── 全局 Agent 锁（Playwright 不支持并发） ──
_agent_lock = threading.Lock()

# ── 全局停止信号（允许前端中断运行中的任务） ──
_stop_event = threading.Event()


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
    global _stop_event
    _stop_event.clear()
    session = _get_or_create_session(sid)
    q = session["queue"]

    try:
        set_emit_target(q)

        session["messages"].append({"role": "user", "content": user_message})

        response = client.chat.completions.create(
            model=config.MODEL_NAME,
            messages=session["messages"],
            tools=tools,
        )
        reply = response.choices[0].message
        session["messages"].append(reply)

        # 工具调用循环
        while reply.tool_calls:
            if _stop_event.is_set():
                q.put({"type": "status", "text": "⏹ Stopped by user."})
                break

            q.put({"type": "status", "text": "Agent 正在工作..."})

            unique_calls = deduplicate_tool_calls(reply.tool_calls)

            for tc in unique_calls:
                if _stop_event.is_set():
                    q.put({"type": "status", "text": "⏹ Stopped by user — skipping remaining tools."})
                    break
                q.put({
                    "type": "tool_call",
                    "tool": tc.function.name,
                    "args": tc.function.arguments or "{}",
                })
                result = execute_tool(tc)
                session["messages"].append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result if not _stop_event.is_set() else "⏹ User interrupted before completion.",
                })

            if _stop_event.is_set():
                break

            skipped = [tc for tc in reply.tool_calls if tc not in unique_calls]
            for tc in skipped:
                session["messages"].append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": "(重复调用已跳过)",
                })

            response = client.chat.completions.create(
                model=config.MODEL_NAME,
                messages=session["messages"],
                tools=tools,
            )
            reply = response.choices[0].message
            session["messages"].append(reply)

        # 获取本轮生成的文件（被中断时不显示文件列表）
        files = get_session_files() if not _stop_event.is_set() else []

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

def _run_pipeline(sid, action, sort_by=None):
    """直接执行 search_jobs + match_jobs 流水线，不经过 LLM 决策。"""
    global _stop_event
    _stop_event.clear()  # 每次新任务重置停止信号
    session = _get_or_create_session(sid)
    q = session["queue"]

    try:
        set_emit_target(q)

        if action == "search_match":
            q.put({"type": "status", "text": "Starting job search..."})
            search_result = search_jobs(sort_by=sort_by)
            q.put({"type": "progress", "text": search_result})

            if _stop_event.is_set():
                q.put({"type": "status", "text": "⏹ Stopped by user."})
                reply = "⏹ Pipeline stopped by user before matching."
            elif not search_result.startswith("❌"):
                q.put({"type": "status", "text": "Starting match analysis..."})
                match_result = match_jobs()
                q.put({"type": "progress", "text": match_result})

                if _stop_event.is_set():
                    q.put({"type": "status", "text": "⏹ Stopped by user."})
                    reply = "⏹ Pipeline stopped by user before resume generation."
                elif not match_result.startswith("错误"):
                    q.put({"type": "status", "text": "Generating direction-based resumes..."})
                    resume_result = generate_resume(by_direction=True)
                    q.put({"type": "progress", "text": resume_result})
                    reply = resume_result
                else:
                    reply = match_result
            else:
                reply = search_result

        else:
            reply = f"Unknown pipeline action: {action}"

        files = get_session_files() if not _stop_event.is_set() else []
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
        kwargs={"sort_by": sort_by},
        daemon=True,
    )
    t.start()

    return jsonify({"status": "started"})


@app.route("/api/stop", methods=["POST"])
def stop():
    """中断当前正在运行的任务。"""
    _stop_event.set()
    return jsonify({"status": "stop_signalled"})


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
        while True:
            try:
                event = q.get(timeout=2)
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                if event.get("type") in ("done", "error"):
                    break
            except queue.Empty:
                # 如果 agent 不忙且队列空，结束流（等下次 chat 再开新流）
                if not session["busy"]:
                    break
                # 每 30 秒发一次 ping 保持连接
                if time.time() - last_ping > 30:
                    yield f"data: {json.dumps({'type': 'ping'})}\n\n"
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
