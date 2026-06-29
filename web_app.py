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

from flask import Flask, request, jsonify, Response, send_from_directory, session

import config
from config import (
    llm_call, set_emit_target, get_session_files, get_system_prompt,
    OUTPUT_DIR, get_current_run_dir, get_latest_run_dir,
    _db_fetch_one, _db_fetch_all, _get_db, emit,
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
app.secret_key = os.environ.get("FLASK_SECRET_KEY", os.urandom(24).hex())

# ── 用户认证 ──

from config import verify_user_password
from functools import wraps

def login_required(f):
    """装饰器：检查用户是否已登录。未登录返回 401。"""
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user" not in session:
            return jsonify({"error": "请先登录"}), 401
        return f(*args, **kwargs)
    return decorated

@app.route("/api/auth/login", methods=["POST"])
def login():
    """用户登录。验证用户名密码，成功后设置 session。"""
    data = request.json or {}
    username = data.get("username", "").strip()
    password = data.get("password", "")
    if not username or not password:
        return jsonify({"error": "用户名和密码不能为空"}), 400
    ok, user = verify_user_password(username, password)
    if not ok:
        return jsonify({"error": "用户名或密码错误"}), 401
    session.clear()
    session["user"] = username
    session["role"] = user["role"]
    session["user_id"] = user["id"]

    # 确保新用户有默认策略
    _ensure_user_strategies(user["id"])

    return jsonify({"status": "ok", "username": username, "role": user["role"]})

@app.route("/api/auth/logout", methods=["POST"])
def logout():
    """登出。清除 session。"""
    session.clear()
    return jsonify({"status": "ok"})

@app.route("/api/auth/status", methods=["GET"])
def auth_status():
    """检查登录状态。"""
    if "user" in session:
        return jsonify({"username": session["user"], "role": session["role"]})
    return jsonify({"username": None, "role": None})

# ── 当前画像名（SQLite 唯一来源）──
def _get_current_user():
    """获取当前活跃用户名。从 SQLite 读取。"""
    try:
        from config import _db_fetch_one
        row = _db_fetch_one(
            "SELECT u.username FROM user_profiles p JOIN users u ON p.user_id = u.id WHERE p.is_current = 1"
        )
        if row:
            return row["username"]
    except Exception:
        pass
    return None

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
                "campaign": None,  # 用户选择的 campaign 名称（str 或 None）
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

        # ── 注入 campaign 配置 ──

        if session.get("campaign"):
            try:
                from config_assembler import load_campaign
                from config import set_campaign_config
                cfg = load_campaign(session["campaign"], user_id=session.get("user_id"))
                set_campaign_config(cfg)
                q.put({"type": "status", "text": f"当前求职方向: {session['campaign']} (策略: {cfg['strategy_name']})"})
            except Exception as e:
                q.put({"type": "progress", "text": f"⚠️ Campaign 加载失败: {e}"})

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

        # ── 注入 campaign 配置（Pipeline 不经过 execute_tool，需显式传入）──
        cfg = None

        if session.get("campaign"):
            try:
                from config_assembler import load_campaign
                cfg = load_campaign(session["campaign"], user_id=session.get("user_id"))
                from config import set_campaign_config
                set_campaign_config(cfg)
                q.put({"type": "status", "text": f"当前求职方向: {session['campaign']} (策略: {cfg['strategy_name']})"})
            except Exception as e:
                q.put({"type": "progress", "text": f"⚠️ Campaign 加载失败: {e}"})

        if action == "search_match":
            q.put({"type": "status", "text": "Starting job search..."})
            search_result = search_jobs(sort_by=sort_by, config=cfg)
            q.put({"type": "progress", "text": search_result})

            if not search_result.startswith("❌"):
                q.put({"type": "status", "text": "Starting match analysis..."})
                match_result = match_jobs(config=cfg, profile=cfg.get("user_profile") if cfg else None)
                q.put({"type": "progress", "text": match_result})

                if not match_result.startswith("错误"):
                    q.put({"type": "status", "text": "Generating direction-based resumes..."})
                    resume_result = generate_resume(by_direction=True, output_langs=languages, profile=cfg.get("user_profile") if cfg else None)
                    q.put({"type": "progress", "text": resume_result})
                    reply = resume_result
                else:
                    reply = match_result
            else:
                reply = search_result

        else:
            reply = f"Unknown pipeline action: {action}"

        # 推送核查报告（review 事件在 done 之前）
        try:
            import resume_gen as _rg
            cr = getattr(_rg, 'last_check_report', [])
            if cr:
                q.put({"type": "review", "bullets": cr, "flagged_count": len(cr)})
            else:
                q.put({"type": "review", "bullets": [], "flagged_count": 0})
        except Exception:
            pass

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


def _run_eval_sse(set_name):
    """对标注数据集运行评估，通过 SSE emit 推送进度。"""
    import json, os, sys
    from config import load_profile
    from config_assembler import load_campaign
    # 确保 evaluation/ 在 sys.path 中，使 eval_core 可从项目根目录导入
    _eval_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "evaluation")
    if _eval_path not in sys.path:
        sys.path.insert(0, _eval_path)
    from eval_core import run_evaluation, is_placeholder_profile

    # 保存 SSE queue 引用
    import config as _cfg
    q = getattr(_cfg._emit_local, "queue", None)

    # ── 1. 加载画像并检查是否为占位模板 ──
    profile = load_profile()
    if is_placeholder_profile(profile):
        emit("⚠️ 用户画像可能为占位模板，评分结果仅供流程验证")

    # ── 2. 加载 Campaign 配置 ──
    CAMPAIGN_NAME = "default"
    config = load_campaign(CAMPAIGN_NAME)
    emit(f"Campaign: {CAMPAIGN_NAME}")

    # ── 3. 调用核心评估流水线 ──
    output_data, result_path = run_evaluation(set_name, profile, config)

    meta = output_data["meta"]
    history = meta.get("history", {})

    # 构建 dir_details（从 results 重新聚合，避免核心模块额外返回）
    dir_counts = {}
    dir_hits = {}
    for r in output_data["results"]:
        d = r["expected_direction"]
        dir_counts[d] = dir_counts.get(d, 0) + 1
        if r.get("direction_correct"):
            dir_hits[d] = dir_hits.get(d, 0) + 1

    # ── 构建前端 SSE summary ──
    files_data = [[fp, desc] for fp, desc in get_session_files()]
    summary = {
        "set_name": set_name,
        "num_cases": meta["num_cases"],
        "direction_accuracy": f"{meta['direction_accuracy']:.1%}",
        "dir_correct": meta["dir_correct"],
        "dir_total": meta["dir_total"],
        "dir_details": {d: f"{dir_hits.get(d, 0)}/{dir_counts[d]}" for d in sorted(dir_counts)},
        "errors": meta["errors"],
        "result_file": os.path.basename(result_path),
        "delta_accuracy": f"{history['arrow']}{abs(history['delta']):.1%}" if history.get("prev_file") else "首次运行",
        "prev_accuracy": f"{history['prev_accuracy']:.1%}" if history.get("prev_accuracy") is not None else None,
        "total_input_tokens": meta["total_input_tokens"],
        "total_output_tokens": meta["total_output_tokens"],
    }
    if q:
        q.put({"type": "done", "reply": json.dumps(summary, ensure_ascii=False), "files": files_data})


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
@login_required
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
@login_required
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


@app.route("/api/eval/files")
def eval_files():
    """列出 output/eval/ 下所有评估结果文件"""
    eval_dir = os.path.join(OUTPUT_DIR, "eval")
    files = []
    if os.path.exists(eval_dir):
        for fname in os.listdir(eval_dir):
            full = os.path.join(eval_dir, fname)
            if os.path.isfile(full):
                files.append({
                    "name": fname,
                    "path": f"eval/{fname}",
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
@login_required
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

            # ── 注入 campaign 配置（与 /api/pipeline 对齐）──
            if session.get("campaign"):
                try:
                    from config_assembler import load_campaign
                    from config import set_campaign_config
                    cfg = load_campaign(session["campaign"], user_id=session.get("user_id"))
                    set_campaign_config(cfg)
                except Exception as e:
                    q.put({"type": "progress", "text": f"⚠️ Campaign 加载失败: {e}"})

            if mode == "job":
                idx = data.get("job_index", 1)
                result = generate_resume(job_index=int(idx), output_langs=languages)
            elif mode == "jd":
                jd = data.get("jd_text", "").strip()
                if not jd:
                    q.put({"type": "error", "text": "JD 文本不能为空"})
                    return
                result = generate_resume(jd_text=jd, output_langs=languages)
            else:
                q.put({"type": "error", "text": f"不支持的简历生成模式: {mode}"})
                return

            # 推送核查报告（review 事件在 done 之前）
            try:
                import resume_gen as _rg
                cr = getattr(_rg, 'last_check_report', [])
                if cr:
                    q.put({"type": "review", "bullets": cr, "flagged_count": len(cr)})
                else:
                    q.put({"type": "review", "bullets": [], "flagged_count": 0})
            except Exception:
                pass  # review 推送失败不影响主流程

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


@app.route("/api/resume/fix", methods=["POST"])
@login_required
def fix_resume_bullet():
    """定点修正单条 resume bullet，返回修正后的完整 Markdown。"""
    data = request.json or {}
    resume_md = data.get("resume_md", "")
    bullet_index = data.get("bullet_index", 0)
    feedback = data.get("feedback", "")

    # 如果前端没传 resume_md，从模块变量读取最近一次生成的简历
    if not resume_md:
        import resume_gen as _rg
        resume_md = getattr(_rg, 'last_resume_md', '')

    if not resume_md or not feedback:
        return jsonify({"error": "Missing resume_md or feedback"}), 400

    try:
        from resume_gen import fix_single_bullet
        from config import load_profile as _lp
        profile = _lp()
        fixed_md = fix_single_bullet(
            original_md=resume_md,
            bullet_index=int(bullet_index),
            user_feedback=feedback,
            profile=profile,
        )
        # 更新模块级变量，供后续操作使用
        import resume_gen as _rg
        _rg.last_resume_md = fixed_md
        # 重新核查修补后的 bullet
        from resume_gen import _parse_source_ids_from_md
        from checker import check_bullet
        parsed = _parse_source_ids_from_md(fixed_md)
        check_result = None
        if parsed and int(bullet_index) < len(parsed):
            b = parsed[int(bullet_index)]
            flags = check_bullet(b["source_ids"], profile or {}, b["text"])
            check_result = {"text": b["text"], "source_ids": b["source_ids"], "flags": flags}
        return jsonify({
            "fixed_md": fixed_md,
            "check_result": check_result,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── 市场调研 API ──

@app.route("/api/market", methods=["POST"])
@login_required
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
@login_required
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


# ── 评估 API ──

@app.route("/api/eval", methods=["POST"])
@login_required
def run_eval_api():
    """运行评估：对标注数据集跑方向预判 + 评分全链路。仅管理员。"""
    if session.get("role") != "admin":
        return jsonify({"error": "仅管理员可运行评估"}), 403

    data = request.json or {}
    sid = data.get("sid", "").strip()
    set_name = data.get("set_name", "").strip()

    if not sid or set_name not in ("dev_set", "holdout"):
        return jsonify({"error": "Missing sid or invalid set_name"}), 400

    session_obj = _get_or_create_session(sid)
    if session_obj["busy"]:
        return jsonify({"error": "Agent is busy"}), 429
    if not _agent_lock.acquire(blocking=False):
        return jsonify({"error": "Another session is running"}), 429
    session_obj["busy"] = True

    q = session_obj["queue"]
    while not q.empty():
        try: q.get_nowait()
        except queue.Empty: break

    def _run():
        try:
            set_emit_target(q)
            _run_eval_sse(set_name)
        except Exception as e:
            q.put({"type": "error", "text": str(e)})
        finally:
            set_emit_target(None)
            session_obj["busy"] = False
            _agent_lock.release()

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"status": "started"})


@app.route("/api/eval/history", methods=["GET"])
@login_required
def eval_history():
    """返回最近一次评估结果摘要。仅管理员。"""
    if session.get("role") != "admin":
        return jsonify({"error": "仅管理员"}), 403

    import json, os
    from config import OUTPUT_DIR

    eval_dir = os.path.join(OUTPUT_DIR, "eval")
    if not os.path.exists(eval_dir):
        return jsonify({})

    result = {}
    for set_name in ("dev_set", "holdout"):
        files = sorted(
            [f for f in os.listdir(eval_dir) if f.startswith(f"eval_{set_name}_")],
            reverse=True,
        )
        if files:
            with open(os.path.join(eval_dir, files[0]), "r", encoding="utf-8") as f:
                data = json.load(f)
            meta = data.get("meta", {})
            result[set_name] = {
                "file": files[0],
                "accuracy": meta.get("direction_accuracy", 0),
                "run_time": meta.get("run_time", ""),
                "num_cases": meta.get("num_cases", 0),
            }
    return jsonify(result)


# ── YAML 配置读写 API ──

@app.route("/api/config/yaml/<name>", methods=["GET"])
def get_yaml_config(name):
    """读取配置文件，返回 JSON 格式内容。me 从 instances/users/ 读取。"""
    if name == "me":
        user_name = _get_current_user()
        if not user_name:
            return jsonify({"error": "未设置当前画像，请在侧边栏选择画像"}), 400
        # 优先从 SQLite 读取
        row = _db_fetch_one(
            "SELECT data FROM user_profiles WHERE is_current = 1"
        )
        if row:
            try:
                data = json.loads(row["data"])
                return jsonify({"name": name, "content": data})
            except json.JSONDecodeError:
                pass
        return jsonify({"error": "用户画像数据读取失败"}), 500
    elif name == "search_config":
        # 优先从 SQLite 读取
        row = _db_fetch_one("SELECT data FROM search_config LIMIT 1")
        if row:
            try:
                data = json.loads(row["data"])
                return jsonify({"name": name, "content": data})
            except json.JSONDecodeError:
                pass
        return jsonify({"error": "系统配置读取失败"}), 500
    else:
        return jsonify({"error": f"不支持的配置文件: {name}"}), 400


@app.route("/api/config/yaml/<name>", methods=["PUT"])
@login_required
def put_yaml_config(name):
    """回写配置文件。me 写入 instances/users/ 下。"""
    data = request.json
    if not data or "content" not in data:
        return jsonify({"error": "Missing content"}), 400

    new_content = data["content"]
    if not isinstance(new_content, dict):
        return jsonify({"error": "content 必须是 JSON 对象"}), 400

    # ── 自定义 dumper：多行文本自动使用块标量 | 风格，避免 \n 转义 ──
    class _MultilineDumper(yaml.Dumper):
        pass

    def _str_representer(dumper, data):
        if '\n' in data:
            return dumper.represent_scalar('tag:yaml.org,2002:str', data, style='|')
        return dumper.represent_scalar('tag:yaml.org,2002:str', data)

    _MultilineDumper.add_representer(str, _str_representer)

    if name == "me":
        user_name = _get_current_user()
        if not user_name:
            return jsonify({"error": "未设置当前画像，请在侧边栏选择画像"}), 400
        # 优先更新 SQLite
        sql_ok = False
        try:
            conn = _get_db()
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE user_profiles SET data = ?, updated_at = CURRENT_TIMESTAMP WHERE is_current = 1",
                (json.dumps(new_content, ensure_ascii=False),)
            )
            conn.commit()
            conn.close()
            sql_ok = True
        except Exception:
            pass
        if sql_ok:
            return jsonify({"status": "ok", "name": name})
        else:
            return jsonify({"error": "写入数据库失败"}), 500
    elif name == "search_config":
        # 更新 SQLite
        sql_ok = False
        try:
            conn = _get_db()
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE search_config SET data = ?, updated_at = CURRENT_TIMESTAMP",
                (json.dumps(new_content, ensure_ascii=False),)
            )
            conn.commit()
            conn.close()
            sql_ok = True
        except Exception:
            pass
        if sql_ok:
            return jsonify({"status": "ok", "name": name})
        else:
            return jsonify({"error": "写入数据库失败"}), 500
    else:
        return jsonify({"error": f"不支持的配置文件: {name}"}), 400


# ── 模型配置 API ──

@app.route("/api/config/model", methods=["GET"])
def get_model_config():
    return jsonify(config.get_model_info())


@app.route("/api/config/model", methods=["POST"])
@login_required
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


# ── Campaign 配置 API ──

@app.route("/api/campaigns", methods=["GET"])
@login_required
def list_campaigns():
    """列出当前用户自己的 Campaign。"""
    user_id = session.get("user_id")
    rows = _db_fetch_all(
        "SELECT id, name, data, created_at FROM campaigns WHERE owner_id = ?",
        (user_id,)
    )
    result = []
    if rows:
        for r in rows:
            try:
                data = json.loads(r["data"])
            except json.JSONDecodeError:
                continue
            sq = data.get("search_queries", [])
            result.append({
                "id": r["id"],
                "name": r["name"],
                "strategy": data.get("strategy", ""),
                "queries": len(sq),
                "keywords": [q.get("keywords", "") for q in sq if q.get("keywords")],
                "created_at": r["created_at"],
            })
    return jsonify(result)


@app.route("/api/session/campaign", methods=["POST"])
@login_required
def set_session_campaign():
    """设置当前 session 的 campaign。传 null 清除选择。"""
    data = request.json or {}
    sid = data.get("sid", "").strip()
    campaign = data.get("campaign")  # 可以是 str 或 None

    if not sid:
        return jsonify({"error": "Missing sid"}), 400

    user_id = session.get("user_id")
    sess = _get_or_create_session(sid)

    # 验证 Campaign 存在（查数据库）
    if campaign is not None:
        row = _db_fetch_one(
            "SELECT name FROM campaigns WHERE name = ? AND owner_id = ?",
            (campaign, user_id)
        )
        if not row:
            return jsonify({"error": f"Campaign '{campaign}' 不存在"}), 400

    sess["campaign"] = campaign
    return jsonify({"status": "ok", "campaign": campaign})


# ── Campaign CRUD API ──

@app.route("/api/campaigns", methods=["POST"])
@login_required
def create_campaign():
    """创建新 Campaign。"""
    data = request.json or {}
    name = data.get("name", "").strip()
    campaign_data = data.get("data", {})
    if not name:
        return jsonify({"error": "Campaign 名称不能为空"}), 400
    if not isinstance(campaign_data, dict):
        return jsonify({"error": "data 必须是 JSON 对象"}), 400
    if not campaign_data.get("strategy"):
        return jsonify({"error": "请选择策略"}), 400

    user_id = session.get("user_id")
    existing = _db_fetch_one("SELECT id FROM campaigns WHERE name = ?", (name,))
    if existing:
        return jsonify({"error": f"Campaign '{name}' 已存在"}), 400

    try:
        conn = _get_db()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO campaigns (name, data, owner_id) VALUES (?, ?, ?)",
            (name, json.dumps(campaign_data, ensure_ascii=False), user_id)
        )
        conn.commit()
        new_id = cursor.lastrowid
        conn.close()
        return jsonify({"status": "ok", "id": new_id, "name": name}), 201
    except Exception as e:
        return jsonify({"error": f"创建失败: {str(e)}"}), 500


@app.route("/api/campaigns/<int:id>", methods=["GET"])
@login_required
def get_campaign(id):
    """获取单个 Campaign 完整数据。"""
    user_id = session.get("user_id")
    row = _db_fetch_one(
        "SELECT id, name, data, created_at, updated_at FROM campaigns WHERE id = ? AND owner_id = ?",
        (id, user_id)
    )
    if not row:
        return jsonify({"error": "Campaign 不存在"}), 404
    try:
        data = json.loads(row["data"])
    except json.JSONDecodeError:
        return jsonify({"error": "数据损坏"}), 500
    return jsonify({
        "id": row["id"],
        "name": row["name"],
        "data": data,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    })


@app.route("/api/campaigns/<int:id>", methods=["PUT"])
@login_required
def update_campaign(id):
    """更新 Campaign。"""
    data = request.json or {}
    name = data.get("name", "").strip()
    campaign_data = data.get("data", {})
    if not name:
        return jsonify({"error": "Campaign 名称不能为空"}), 400
    if not isinstance(campaign_data, dict):
        return jsonify({"error": "data 必须是 JSON 对象"}), 400

    user_id = session.get("user_id")
    row = _db_fetch_one(
        "SELECT id FROM campaigns WHERE id = ? AND owner_id = ?",
        (id, user_id)
    )
    if not row:
        return jsonify({"error": "Campaign 不存在"}), 404

    existing = _db_fetch_one("SELECT id FROM campaigns WHERE name = ? AND id != ?", (name, id))
    if existing:
        return jsonify({"error": f"名称 '{name}' 已被其他 Campaign 使用"}), 400

    try:
        conn = _get_db()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE campaigns SET name = ?, data = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND owner_id = ?",
            (name, json.dumps(campaign_data, ensure_ascii=False), id, user_id)
        )
        conn.commit()
        conn.close()
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"error": f"更新失败: {str(e)}"}), 500


@app.route("/api/campaigns/<int:id>", methods=["DELETE"])
@login_required
def delete_campaign(id):
    """删除 Campaign。"""
    user_id = session.get("user_id")
    row = _db_fetch_one(
        "SELECT id FROM campaigns WHERE id = ? AND owner_id = ?",
        (id, user_id)
    )
    if not row:
        return jsonify({"error": "Campaign 不存在"}), 404
    try:
        conn = _get_db()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM campaigns WHERE id = ? AND owner_id = ?", (id, user_id))
        conn.commit()
        conn.close()
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"error": f"删除失败: {str(e)}"}), 500


# ── 策略 CRUD API ──

def _ensure_user_strategies(user_id):
    """确保用户拥有自己的策略副本。如果没有，从已有策略中复制。"""
    count = _db_fetch_one(
        "SELECT COUNT(*) as cnt FROM strategies WHERE owner_id = ?", (user_id,)
    )
    if count and count["cnt"] > 0:
        return  # 已有策略，跳过

    defaults = _db_fetch_all(
        "SELECT name, description, data FROM strategies WHERE owner_id IS NOT NULL ORDER BY id LIMIT 20"
    )

    if not defaults:
        return  # 没有任何默认策略

    conn = _get_db()
    cursor = conn.cursor()
    copied = 0
    for d in defaults:
        # 检查用户是否已有同名策略
        exist = cursor.execute(
            "SELECT id FROM strategies WHERE name = ? AND owner_id = ?",
            (d["name"], user_id)
        ).fetchone()
        if exist:
            continue
        cursor.execute(
            "INSERT INTO strategies (name, description, data, owner_id) VALUES (?, ?, ?, ?)",
            (d["name"], d["description"], d["data"], user_id)
        )
        copied += 1
    conn.commit()
    conn.close()
    if copied:
        print(f"[策略种子] 为用户 {user_id} 复制了 {copied} 个默认策略")


@app.route("/api/strategies", methods=["GET"])
@login_required
def list_strategies():
    """列出当前用户的策略 + 全局默认策略（供 campaign 编辑下拉使用）。"""
    user_id = session.get("user_id")
    rows = _db_fetch_all(
        "SELECT id, name, description, data, created_at "
        "FROM strategies WHERE owner_id = ? "
        "ORDER BY id",
        (user_id,)
    )
    result = []
    for r in rows:
        try:
            data = json.loads(r["data"])
        except json.JSONDecodeError:
            continue
        result.append({
            "id": r["id"],
            "name": r["name"],
            "description": r["description"],
            "data": data,
            "created_at": r["created_at"],
        })
    return jsonify(result)


@app.route("/api/strategies", methods=["POST"])
@login_required
def create_strategy():
    """创建新策略。验证五维权重之和等于 100。"""
    data = request.json or {}
    name = data.get("name", "").strip()
    description = data.get("description", "")
    strategy_data = data.get("data", {})

    if not name:
        return jsonify({"error": "策略名称不能为空"}), 400
    if not isinstance(strategy_data, dict):
        return jsonify({"error": "data 必须是 JSON 对象"}), 400

    wp = strategy_data.get("weight_profile", {})
    if wp:
        total = sum(wp.values())
        if total != 100:
            return jsonify({"error": f"五维权重之和必须等于 100，当前为 {total}"}), 400

    user_id = session.get("user_id")
    existing = _db_fetch_one(
        "SELECT id FROM strategies WHERE name = ? AND owner_id = ?",
        (name, user_id)
    )
    if existing:
        return jsonify({"error": f"策略 '{name}' 已存在"}), 400

    try:
        conn = _get_db()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO strategies (name, description, data, owner_id) "
            "VALUES (?, ?, ?, ?)",
            (name, description, json.dumps(strategy_data, ensure_ascii=False), user_id)
        )
        conn.commit()
        new_id = cursor.lastrowid
        conn.close()
        return jsonify({"status": "ok", "id": new_id, "name": name}), 201
    except Exception as e:
        return jsonify({"error": f"创建失败: {str(e)}"}), 500


@app.route("/api/strategies/<int:id>", methods=["GET"])
@login_required
def get_strategy(id):
    """获取单个策略（仅限自己的或全局默认）。"""
    user_id = session.get("user_id")
    row = _db_fetch_one(
        "SELECT id, name, description, data, created_at, updated_at "
        "FROM strategies WHERE id = ? AND owner_id = ?",
        (id, user_id)
    )
    if not row:
        return jsonify({"error": "策略不存在"}), 404
    try:
        data = json.loads(row["data"])
    except json.JSONDecodeError:
        return jsonify({"error": "数据损坏"}), 500
    return jsonify({
        "id": row["id"],
        "name": row["name"],
        "description": row["description"],
        "data": data,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    })


@app.route("/api/strategies/<int:id>", methods=["PUT"])
@login_required
def update_strategy(id):
    """更新策略（仅限自己的策略）。"""
    data = request.json or {}
    name = data.get("name", "").strip()
    description = data.get("description", "")
    strategy_data = data.get("data", {})

    if not name:
        return jsonify({"error": "策略名称不能为空"}), 400
    if not isinstance(strategy_data, dict):
        return jsonify({"error": "data 必须是 JSON 对象"}), 400

    wp = strategy_data.get("weight_profile", {})
    if wp:
        total = sum(wp.values())
        if total != 100:
            return jsonify({"error": f"五维权重之和必须等于 100，当前为 {total}"}), 400

    user_id = session.get("user_id")
    row = _db_fetch_one(
        "SELECT id FROM strategies WHERE id = ? AND owner_id = ?",
        (id, user_id)
    )
    if not row:
        return jsonify({"error": "策略不存在或无权编辑"}), 404

    existing = _db_fetch_one(
        "SELECT id FROM strategies WHERE name = ? AND owner_id = ? AND id != ?",
        (name, user_id, id)
    )
    if existing:
        return jsonify({"error": f"名称 '{name}' 已被其他策略使用"}), 400

    try:
        conn = _get_db()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE strategies SET name = ?, description = ?, data = ?, "
            "updated_at = CURRENT_TIMESTAMP WHERE id = ? AND owner_id = ?",
            (name, description, json.dumps(strategy_data, ensure_ascii=False), id, user_id)
        )
        conn.commit()
        conn.close()
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"error": f"更新失败: {str(e)}"}), 500


@app.route("/api/strategies/<int:id>", methods=["DELETE"])
@login_required
def delete_strategy(id):
    """删除策略（仅限自己的，且不能是被 Campaign 引用的）。"""
    user_id = session.get("user_id")
    row = _db_fetch_one(
        "SELECT id, name FROM strategies WHERE id = ? AND owner_id = ?",
        (id, user_id)
    )
    if not row:
        return jsonify({"error": "策略不存在或无权删除"}), 404

    # 检查是否有 Campaign 引用此策略
    usage = _db_fetch_one(
        "SELECT COUNT(*) as cnt FROM campaigns WHERE owner_id = ? "
        "AND json_extract(data, '$.strategy') = ?",
        (user_id, row["name"])
    )
    if usage and usage["cnt"] > 0:
        return jsonify({
            "error": f"该策略正被 {usage['cnt']} 个求职方向使用，请先修改那些方向的策略选择后再删除"
        }), 400

    try:
        conn = _get_db()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM strategies WHERE id = ? AND owner_id = ?", (id, user_id))
        conn.commit()
        conn.close()
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"error": f"删除失败: {str(e)}"}), 500


# ── 用户画像 API ──

@app.route("/api/users", methods=["GET"])
def list_users():
    """列出所有可用用户画像。优先从 SQLite 读取。"""
    rows = _db_fetch_all("SELECT name, data FROM user_profiles")
    if rows:
        result = []
        for r in rows:
            try:
                profile = json.loads(r["data"])
                user_name = profile.get("name", r["name"])
            except json.JSONDecodeError:
                user_name = r["name"]
            result.append({
                "name": r["name"],
                "user_name": user_name,
            })
        return jsonify(result)
    return jsonify([])


@app.route("/api/config/user", methods=["POST"])
@login_required
def set_config_user():
    """切换当前活跃画像。更新 SQLite。"""
    data = request.json or {}
    new_user = data.get("user", "").strip()
    if not new_user:
        return jsonify({"error": "user 不能为空"}), 400

    # 验证画像存在
    row = _db_fetch_one(
        "SELECT name FROM user_profiles WHERE name = ?", (new_user,)
    )
    if not row:
        return jsonify({"error": f"画像不存在: {new_user}"}), 400

    # 更新 SQLite
    try:
        conn = _get_db()
        cursor = conn.cursor()
        cursor.execute("UPDATE user_profiles SET is_current = 0")
        cursor.execute(
            "UPDATE user_profiles SET is_current = 1 WHERE name = ?", (new_user,)
        )
        conn.commit()
        conn.close()
    except Exception:
        pass

    return jsonify({"status": "ok", "user": new_user})


@app.route("/download/<path:filepath>")
def download(filepath):
    return send_from_directory("output", filepath, as_attachment=True)


# ============================================================
#  Cleanup
# ============================================================

atexit.register(cleanup_playwright)
atexit.register(cleanup_renderer)


# ── 当前用户信息 API ──

@app.route("/api/user/current", methods=["GET"])
def get_current_user_info():
    """返回当前用户信息。优先从 session 获取，否则回退到数据库标记。"""
    if "user" in session:
        return jsonify({"username": session["user"], "role": session["role"]})
    user_name = _get_current_user()
    if not user_name:
        return jsonify({"username": None, "role": None})
    row = _db_fetch_one(
        "SELECT username, role FROM users WHERE username = ?", (user_name,)
    )
    if row:
        return jsonify({"username": row["username"], "role": row["role"]})
    return jsonify({"username": user_name, "role": "user"})


# ── 用户画像 Schema API ──

@app.route("/api/schema/user_field", methods=["GET"])
def get_user_field_schema():
    """返回用户画像字段定义 Schema。从 SQLite 读取。"""
    row = _db_fetch_one(
        "SELECT data FROM field_schemas WHERE name = 'user_field'"
    )
    if row:
        try:
            schema = json.loads(row["data"])
            return jsonify(schema)
        except json.JSONDecodeError:
            pass
    return jsonify({"error": "Schema 配置读取失败"}), 500


@app.route("/api/schema/user_field", methods=["PUT"])
@login_required
def put_user_field_schema():
    """更新用户画像字段定义 Schema。仅管理员可操作。"""
    user_name = _get_current_user()
    if not user_name:
        return jsonify({"error": "未登录"}), 401
    row = _db_fetch_one(
        "SELECT role FROM users WHERE username = ?", (user_name,)
    )
    if not row or row["role"] != "admin":
        return jsonify({"error": "仅管理员可修改字段定义"}), 403

    data = request.json
    if not data:
        return jsonify({"error": "请求体为空"}), 400
    if "groups" not in data:
        return jsonify({"error": "Schema 必须包含 groups 字段"}), 400

    sql_ok = False
    try:
        conn = _get_db()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE field_schemas SET data = ?, updated_by = (SELECT id FROM users WHERE username = ?), updated_at = CURRENT_TIMESTAMP WHERE name = 'user_field'",
            (json.dumps(data, ensure_ascii=False), user_name)
        )
        conn.commit()
        conn.close()
        sql_ok = True
    except Exception:
        pass

    if sql_ok:
        return jsonify({"status": "ok"})
    else:
        return jsonify({"error": "写入 Schema 失败"}), 500


# ============================================================
#  Main
# ============================================================

if __name__ == "__main__":
    print("=" * 50)
    print("  JobsDB Agent Web UI")
    print("  http://127.0.0.1:5000")
    print("=" * 50)
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)
