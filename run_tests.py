"""
run_tests.py — 自动化测试入口
覆盖：Pydantic Schema / JSON 解析容错 / Prompt 模板引擎 / Checker 事实核查 / Prompt 完整性
用法: python run_tests.py
所有测试不调用 LLM、不写数据库、不修改任何文件。
"""
import sys
import os
import re

# 确保项目根目录在 path 中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import yaml

try:
    from config import parse_json_response, render_prompt, load_prompts
except Exception as e:
    print(f"[FATAL] 无法导入 config 模块: {e}")
    print("请确保 .env 中已配置 API Key，且 data/job_agent.db 数据库已初始化。")
    sys.exit(1)

from checker import check_bullet

from engine.contracts.match_result import MatchResult, Scores
from engine.contracts.market_result import MarketAnalysisResult, TechnicalSkill
from engine.contracts.resume import Resume, ResumeBullet
from engine.contracts.gap_result import GapAnalysisResult
from engine.contracts.direction_result import DirectionAggregationResult
from engine.contracts.review_result import ResumeReviewResult


# ============================================================
#  测试辅助
# ============================================================

_passed = 0
_failed = 0
_failures = []

# Windows 终端可能不支持 emoji/Unicode 特殊字符，使用纯 ASCII 标记
_PASS_MARK = "PASS"
_FAIL_MARK = "FAIL"


def check(name, condition, detail=""):
    """断言一个条件，记录通过/失败。"""
    global _passed, _failed, _failures
    if condition:
        _passed += 1
        print(f"  [{_PASS_MARK}] {name}")
    else:
        _failed += 1
        msg = f"  [{_FAIL_MARK}] {name}"
        if detail:
            msg += f"  -- {detail}"
        print(msg)
        _failures.append(msg)


def load_mock_profile():
    """加载 mock_me.yaml 作为 checker 测试的模拟用户画像。"""
    path = os.path.join(os.path.dirname(__file__), "instances", "eval", "mock_me.yaml")
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# ============================================================
#  1. Pydantic Schema 验证
# ============================================================

def test_pydantic_schemas():
    """验证所有 Pydantic 模型能正确校验合法/非法输入。"""
    print("\n── 1. Pydantic Schema 验证 ──")

    # 1a: Scores — 合法离散值 (95/80/60/40/20)
    try:
        s = Scores(skill=95, experience=80, level=60, industry=40, bonus=20)
        check("Scores 合法离散值 (95/80/60/40/20)", True)
    except Exception as e:
        check("Scores 合法离散值 (95/80/60/40/20)", False, str(e))

    # 1b: Scores — 非法离散值 85 应被拒绝
    try:
        Scores(skill=85, experience=80, level=60, industry=40, bonus=20)
        check("Scores 拒绝非法离散值 85", False, "应抛出 ValidationError 但未抛出")
    except Exception:
        check("Scores 拒绝非法离散值 85", True)

    # 1c: Scores — 超出范围的值 100 应拒绝
    try:
        Scores(skill=100, experience=80, level=60, industry=40, bonus=20)
        check("Scores 拒绝超范围值 100", False, "应抛出 ValidationError 但未抛出")
    except Exception:
        check("Scores 拒绝超范围值 100", True)

    # 1d: Scores — 字符串应拒绝
    try:
        Scores(skill="95", experience=80, level=60, industry=40, bonus=20)  # pyright: ignore
        check("Scores 拒绝字符串 '95'", False, "应抛出 ValidationError 但未抛出")
    except Exception:
        check("Scores 拒绝字符串 '95'", True)

    # 1e: MatchResult — 合法输入
    try:
        m = MatchResult(
            reason="候选人技能与岗位高度匹配",
            scores=Scores(skill=95, experience=80, level=60, industry=40, bonus=20),
        )
        check("MatchResult 合法输入", True)
    except Exception as e:
        check("MatchResult 合法输入", False, str(e))

    # 1f: MatchResult — 缺少必填字段 scores 应拒绝
    try:
        MatchResult(reason="test")  # pyright: ignore
        check("MatchResult 缺少 scores 应拒绝", False, "应抛出 ValidationError")
    except Exception:
        check("MatchResult 缺少 scores 应拒绝", True)

    # 1g: ResumeBullet — 合法输入（含 source_ids）
    rb = ResumeBullet(text="Developed RESTful API handling 5000 req/s", source_ids=["exp_001", "exp_002"])
    check("ResumeBullet 合法输入",
          rb.text == "Developed RESTful API handling 5000 req/s" and rb.source_ids == ["exp_001", "exp_002"])

    # 1h: ResumeBullet — 默认空 source_ids
    rb = ResumeBullet(text="Built payment system")
    check("ResumeBullet 默认空 source_ids",
          rb.source_ids == [])

    # 1i: Resume — 完整合法输入
    try:
        r = Resume(
            summary="Experienced backend engineer with 5 years in fintech.",
            skills="Python, Java, AWS, Docker, PostgreSQL",
            work_experience=[
                ResumeBullet(text="Built payment gateway processing $10M/month", source_ids=["exp_001"]),
                ResumeBullet(text="Led migration from monolith to microservices", source_ids=["exp_002"]),
            ],
            projects=[ResumeBullet(text="Open-source CI/CD tool with 500+ GitHub stars")],
            education="BSc Computer Science, University of Hong Kong",
            certifications="AWS Solutions Architect Associate",
        )
        check("Resume 完整合法输入", True)
    except Exception as e:
        check("Resume 完整合法输入", False, str(e))

    # 1j: MarketAnalysisResult — 含 TechnicalSkill 子模型
    try:
        mar = MarketAnalysisResult(
            sample_size=10,
            technical_skills=[
                TechnicalSkill(
                    skill="Python",
                    category="编程语言",
                    description="Python programming language for backend and data processing",
                    typical_tools=["Django", "FastAPI", "Pandas"],
                    count=8,
                    percentage="80%",
                    level="必须",
                )
            ],
        )
        check("MarketAnalysisResult 含 TechnicalSkill", True)
    except Exception as e:
        check("MarketAnalysisResult 含 TechnicalSkill", False, str(e))

    # 1k: GapAnalysisResult — 最小合法输入
    try:
        gar = GapAnalysisResult(
            strategic_advice=["优先补强 K8s 和 AWS EKS 实操经验"],
        )
        check("GapAnalysisResult 最小合法输入", True)
    except Exception as e:
        check("GapAnalysisResult 最小合法输入", False, str(e))

    # 1l: DirectionAggregationResult — 合法输入
    try:
        dar = DirectionAggregationResult(
            direction="web3",
            typical_responsibilities=["Design and implement smart contracts", "Build DApp frontend"],
            common_bonus=["Solidity", "Rust"],
            resume_strategy="突出 WaaS 和智能合约交互实战经验，弱化传统后端技术栈",
        )
        check("DirectionAggregationResult 合法输入", True)
    except Exception as e:
        check("DirectionAggregationResult 合法输入", False, str(e))

    # 1m: ResumeReviewResult — 合法输入
    try:
        rrr = ResumeReviewResult(
            overall_score="B",
            six_second_test="pass — 关键信息在首屏可见",
            missing_keywords=["Kubernetes", "gRPC"],
            top_3_improvements=["增加量化数据", "缩减 Summary 长度", "技能按 JD 重排序"],
        )
        check("ResumeReviewResult 合法输入", True)
    except Exception as e:
        check("ResumeReviewResult 合法输入", False, str(e))


# ============================================================
#  2. JSON 解析容错
# ============================================================

def test_parse_json_response():
    """验证 parse_json_response() 多层容错策略：
    策略1: 去除 ``` 代码块包裹 → json.loads
    策略2: find('[') / rfind(']') 截取数组
    策略3: find('{') / rfind('}') 截取对象
    """
    print("\n── 2. JSON 解析容错 ──")

    # 2a: 标准 JSON 对象
    result = parse_json_response('{"key": "value"}')
    check("标准 JSON 对象", result == {"key": "value"},
          f"得到 {result}")

    # 2b: 标准 JSON 数组
    result = parse_json_response('[1, 2, 3]')
    check("标准 JSON 数组", result == [1, 2, 3],
          f"得到 {result}")

    # 2c: ```json 代码块包裹
    result = parse_json_response('```json\n{"a": 1}\n```')
    check("Markdown ```json 代码块", result == {"a": 1},
          f"得到 {result}")

    # 2d: ``` 无语言标注
    result = parse_json_response('```\n{"b": 2}\n```')
    check("Markdown 无语言标注代码块", result == {"b": 2},
          f"得到 {result}")

    # 2e: JSON 对象嵌在前后文字中（策略3: find '{' / rfind '}'）
    result = parse_json_response('以下是分析结果：\n{"result": "ok", "score": 85}\n请确认。')
    check("文字中提取 JSON 对象", result == {"result": "ok", "score": 85},
          f"得到 {result}")

    # 2f: JSON 数组嵌在前后文字中（策略2: find '[' / rfind ']'）
    result = parse_json_response('结果是：[1, 2, 3]，请确认')
    check("文字中提取 JSON 数组", result == [1, 2, 3],
          f"得到 {result}")

    # 2g: 嵌套花括号 — 最外层对象
    result = parse_json_response('{"data": {"nested": true, "items": [1,2]}}')
    check("嵌套 JSON 对象", result == {"data": {"nested": True, "items": [1, 2]}},
          f"得到 {result}")

    # 2h: 嵌套数组 — 最外层数组
    result = parse_json_response('[{"id": 1}, {"id": 2}, {"id": 3}]')
    check("JSON 对象数组", result == [{"id": 1}, {"id": 2}, {"id": 3}],
          f"得到 {result}")

    # 2i: ```json 代码块含嵌套数组
    result = parse_json_response('```json\n{"items": [{"id": 1}, {"id": 2}]}\n```')
    check("Markdown 代码块含嵌套数组", result == {"items": [{"id": 1}, {"id": 2}]},
          f"得到 {result}")

    # 2j: 纯文本无 JSON → None
    result = parse_json_response('这是一段纯文本，没有任何 JSON 结构')
    check("纯文本返回 None", result is None,
          f"得到 {result}")

    # 2k: 空字符串 → None
    result = parse_json_response('')
    check("空字符串返回 None", result is None,
          f"得到 {result}")

    # 2l: 只有左花括号 → None
    result = parse_json_response('{"a": 1')
    check("花括号不匹配返回 None", result is None,
          f"得到 {result}")

    # 2m: 方括号和花括号都不闭合 → None（无法提取任何有效 JSON）
    result = parse_json_response('[{"a": 1')
    check("括号全不闭合返回 None", result is None,
          f"得到 {result}")

    # 2n: 非法 JSON 语法 → None
    result = parse_json_response('{a: 1}')
    check("非法 JSON 语法返回 None", result is None,
          f"得到 {result}")

    # 2o: LLM 常见输出 — JSON 后有补充说明
    result = parse_json_response('{"match": true, "reason": "技能高度匹配"}\n\n如果需要更多分析，请告诉我。')
    check("JSON 后有补述文字", result == {"match": True, "reason": "技能高度匹配"},
          f"得到 {result}")

    # 2p: 中文引号干扰（确保标准 JSON 解析不被中文标点干扰）
    result = parse_json_response('{"title": "高级Java开发工程师", "score": 80}')
    check("JSON 值含中文", result == {"title": "高级Java开发工程师", "score": 80},
          f"得到 {result}")


# ============================================================
#  3. Prompt 模板引擎
# ============================================================

def test_render_prompt():
    """验证 render_prompt() 占位符替换逻辑。
    占位符使用 <key> 尖括号格式，避免与 JSON {} 冲突。
    """
    print("\n── 3. Prompt 模板引擎 ──")

    # 3a: 单个占位符
    result = render_prompt("你好 <name>，欢迎使用", name="张三")
    check("单个占位符", result == "你好 张三，欢迎使用",
          f"得到: {result}")

    # 3b: 多个不同占位符
    result = render_prompt("<greeting> <name>，<status>",
                           greeting="Hello", name="World", status="今天晴天")
    check("多个不同占位符", result == "Hello World，今天晴天",
          f"得到: {result}")

    # 3c: 重复占位符全部替换
    result = render_prompt("<x> + <x> = <y>", x="a", y="b")
    check("重复占位符全部替换", result == "a + a = b",
          f"得到: {result}")

    # 3d: 无占位符 — 原样返回
    result = render_prompt("这是一段没有占位符的文本")
    check("无占位符原样返回", result == "这是一段没有占位符的文本",
          f"得到: {result}")

    # 3e: 整数参数自动转字符串
    result = render_prompt("Top <n> results", n=10)
    check("整数自动转字符串", result == "Top 10 results",
          f"得到: {result}")

    # 3f: 占位符与 JSON {} 混用不冲突
    result = render_prompt('方向: <direction>\n格式: {"key": "value", "num": 42}',
                           direction="web3")
    check("占位符与 JSON 花括号不冲突",
          result == '方向: web3\n格式: {"key": "value", "num": 42}',
          f"得到: {result}")

    # 3g: 缺少参数时占位符保留原样（不崩溃、不抛异常）
    result = render_prompt("Hello <name>, age <age>", name="Alice")
    check("缺参占位符保留原样", result == "Hello Alice, age <age>",
          f"得到: {result}")

    # 3h: 空字符串替换
    result = render_prompt("prefix_<middle>_suffix", middle="")
    check("空字符串替换", result == "prefix__suffix",
          f"得到: {result}")

    # 3i: 占位符本身包含下划线
    result = render_prompt("权重: <weight_profile>", weight_profile="payment")
    check("占位符含下划线", result == "权重: payment",
          f"得到: {result}")

    # 3j: 多行模板替换
    tpl = "岗位: <title>\n方向: <direction>\n评分: <score>"
    result = render_prompt(tpl, title="Backend Developer", direction="payment", score="84")
    check("多行模板替换",
          result == "岗位: Backend Developer\n方向: payment\n评分: 84",
          f"得到: {result}")


# ============================================================
#  4. Checker 事实核查
# ============================================================

def test_check_bullet():
    """验证 check_bullet() 七种 flag 检测，使用 mock_me.yaml 模拟用户画像。

    mock_me.yaml 结构:
      experiences:
        - id: resp_order_dev       text: "参与订单系统开发与维护"
        - id: resp_unit_test       text: "负责编写单元测试"
        - id: resp_risk            text: "主导风控系统建设"
        - id: resp_api_dev         text: "负责 RESTful API 的设计与开发"
        - id: resp_db_opt          text: "参与 MySQL 数据库优化，将查询响应时间从 2 秒降至 0.3 秒"
        - id: resp_team_lead       text: "带领 3 人小组完成支付模块开发"
        - id: resp_user_growth     text: "协助产品团队完成用户增长 298%"
        - id: resp_code_review     text: "参与代码评审"
        ...
    """
    print("\n── 4. Checker 事实核查 ──")
    profile = load_mock_profile()

    # ── 4a: empty_source — source_ids 为空 ──
    flags = check_bullet([], profile,
                         "Developed RESTful API handling 5000 requests/sec")
    check("empty_source — 空 source_ids",
          flags == ["empty_source"],
          f"flags={flags}")

    # ── 4b: dangling_reference — 引用不存在的 id ──
    flags = check_bullet(["nonexistent_abc_123"], profile,
                         "Built payment system processing 10000 transactions")
    check("dangling_reference — 引用不存在的 id",
          "dangling_reference" in flags,
          f"flags={flags}")

    # ── 4c: placeholder_present — [TODO] 残留 ──
    flags = check_bullet(["resp_order_dev"], profile,
                         "Led platform migration [TODO: add specific metric]")
    check("placeholder_present — [TODO] 残留",
          "placeholder_present" in flags,
          f"flags={flags}")

    # ── 4d: placeholder_present — 中文【待补充】残留 ──
    flags = check_bullet(["resp_unit_test"], profile,
                         "负责测试覆盖率达到【待补充】%")
    check("placeholder_present — 【待补充】残留",
          "placeholder_present" in flags,
          f"flags={flags}")

    # ── 4e: number_not_found — 源无数字，bullet 有数字 ──
    # resp_order_dev: "参与订单系统开发与维护" — 无任何数字
    flags = check_bullet(["resp_order_dev"], profile,
                         "处理 5000 笔交易订单")
    check("number_not_found — 源无数字、bullet 有数字",
          "number_not_found" in flags,
          f"flags={flags}")

    # ── 4f: number_conflict — 精确数字矛盾 ──
    # resp_db_opt 源: "…2 秒降至 0.3 秒" → bullet 写成 5 秒和 0.1 秒
    flags = check_bullet(["resp_db_opt"], profile,
                         "将查询响应时间从 5 秒降至 0.1 秒")
    check("number_conflict — 精确数字矛盾 (2秒→5秒, 0.3秒→0.1秒)",
          "number_conflict" in flags,
          f"flags={flags}")

    # ── 4g: approx_out_of_range — 约数偏差超过 5% ──
    # resp_user_growth 源: "用户增长 298%" → bullet 写 "约 50%"，偏差 83% > 5%
    flags = check_bullet(["resp_user_growth"], profile,
                         "协助产品团队完成约 50% 用户增长")
    check("approx_out_of_range — 约数 50% vs 源 298%（偏差 83% > 5%）",
          "approx_out_of_range" in flags,
          f"flags={flags}")

    # ── 4h: strength_upgrade — 动词强度升级 ──
    # resp_code_review 源: "参与代码评审" — 动词 "参与" 强度 1
    # bullet: "主导" — 强度 3，明显超出源数据支撑
    flags = check_bullet(["resp_code_review"], profile,
                         "主导代码评审体系搭建")
    check("strength_upgrade — 参与→主导 (强度 1→3)",
          "strength_upgrade" in flags,
          f"flags={flags}")

    # ── 4i: 干净 bullet — 完全相同的内容，无任何 flag ──
    # resp_api_dev 源: "负责 RESTful API 的设计与开发"
    flags = check_bullet(["resp_api_dev"], profile,
                         "负责 RESTful API 的设计与开发")
    check("干净 bullet — 无任何 flag",
          flags == [],
          f"flags={flags}")

    # ── 4j: 数字完全匹配 — 无数字 flag ──
    # resp_db_opt 源和 bullet 的数字一致: 2 秒 → 0.3 秒
    flags = check_bullet(["resp_db_opt"], profile,
                         "将查询响应时间从 2 秒降至 0.3 秒")
    check("数字完全匹配 — 无数字 flag",
          not any(f in flags for f in ["number_not_found", "number_conflict", "approx_out_of_range"]),
          f"flags={flags}")

    # ── 4k: 强度匹配 — 相同动词强度不触发 strength_upgrade ──
    # resp_unit_test 源: "负责编写单元测试" — "负责"(2) + "编写"(2)，max=2
    # bullet: 同样含 "负责" 和 "编写"，max=2，未升级
    flags = check_bullet(["resp_unit_test"], profile,
                         "负责编写单元测试覆盖")
    check("强度匹配 — 不触发 strength_upgrade",
          "strength_upgrade" not in flags,
          f"flags={flags}")

    # ── 4l: 复合场景 — 同时检出 dangling_reference + placeholder ──
    flags = check_bullet(["resp_order_dev", "fake_id_xyz"], profile,
                         "参与系统开发 [TBD: review required]")
    check("复合场景 — dangling_reference + placeholder_present",
          "dangling_reference" in flags and "placeholder_present" in flags,
          f"flags={flags}")


# ============================================================
#  5. Prompt 完整性检查
# ============================================================

def test_prompt_completeness():
    """验证 prompts.yaml 结构完整、占位符格式正确。"""
    print("\n── 5. Prompt 完整性 ──")

    prompts = load_prompts()

    # 5a: 文件可加载且非空
    check("prompts.yaml 可加载", bool(prompts),
          "文件为空或不存在" if not prompts else "")

    # 5b: 必需顶层 section 存在
    required_sections = ["agent", "job_match", "market_analysis", "resume"]
    for section in required_sections:
        check(f"顶层 section: {section}",
              section in prompts,
              f"缺失 section: {section}")

    # 5c: agent.system_prompt 存在且非空
    agent_sp = prompts.get("agent", {}).get("system_prompt", "")
    check("agent.system_prompt 存在且非空",
          bool(agent_sp and agent_sp.strip()),
          f"长度: {len(agent_sp)}")

    # 5d: job_match 关键 prompt
    scoring = prompts.get("job_match", {}).get("scoring_system_prompt", "")
    check("job_match.scoring_system_prompt 存在且非空",
          bool(scoring and scoring.strip()),
          f"长度: {len(scoring)}")

    direction = prompts.get("job_match", {}).get("direction_classification_prompt", "")
    check("job_match.direction_classification_prompt 存在且非空",
          bool(direction and direction.strip()),
          f"长度: {len(direction)}")

    # 5e: market_analysis 关键 prompt
    analysis = prompts.get("market_analysis", {}).get("analysis_system_prompt", "")
    check("market_analysis.analysis_system_prompt 存在且非空",
          bool(analysis and analysis.strip()),
          f"长度: {len(analysis)}")

    # 5f: resume 关键 prompt
    for key in ["base_rules", "prompt_for_job", "prompt_for_jd_text", "resume_review_prompt"]:
        val = prompts.get("resume", {}).get(key, "")
        check(f"resume.{key} 存在且非空",
              bool(val and val.strip()),
              f"长度: {len(val)}")

    # 5g: 所有模板字符串中 < > 括号配对检查
    def _find_unbalanced(text):
        """检查 < > 配对。仅报告未闭合的 <——单独的 > 在文本中是合法的。"""
        depth = 0
        for ch in text:
            if ch == '<':
                depth += 1
            elif ch == '>':
                if depth > 0:
                    depth -= 1
                # depth == 0 时出现的 > 是普通文本字符，忽略
        return f"共 {depth} 个未闭合的 <" if depth > 0 else None

    def _collect_all_templates(data, path=""):
        """递归收集所有字符串叶子节点及其 yaml 路径。"""
        items = []
        if isinstance(data, dict):
            for k, v in data.items():
                items.extend(_collect_all_templates(v, f"{path}.{k}" if path else k))
        elif isinstance(data, str) and len(data) > 10:
            items.append((path, data))
        return items

    all_templates = _collect_all_templates(prompts)
    unbalanced_paths = []
    for tpl_path, tpl_text in all_templates:
        err = _find_unbalanced(tpl_text)
        if err:
            unbalanced_paths.append((tpl_path, err))

    if unbalanced_paths:
        for tpl_path, err in unbalanced_paths:
            check(f"括号配对: {tpl_path}", False, err)
    else:
        check(f"所有 {len(all_templates)} 个模板 < > 括号配对正确", True)


# ============================================================
#  入口
# ============================================================

def main():
    global _passed, _failed, _failures

    print("=" * 60)
    print("  JobPilot 自动化测试")
    print("=" * 60)
    print("  覆盖: Pydantic Schema / JSON 解析 / 模板引擎 / Checker / Prompt 完整性")
    print("  注意: 所有测试不调用 LLM、不写数据库、不修改文件")
    print()

    test_pydantic_schemas()
    test_parse_json_response()
    test_render_prompt()
    test_check_bullet()
    test_prompt_completeness()

    total = _passed + _failed
    print(f"\n{'='*60}")
    print(f"  结果: {_passed}/{total} 通过", end="")
    if _failed > 0:
        print(f"，{_failed} 失败")
    else:
        print(" -- 全部通过")
    print(f"{'='*60}")

    if _failures:
        print(f"\n  失败明细:")
        for f in _failures:
            print(f"    {f}")

    return 0 if _failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
