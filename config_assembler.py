"""
config_assembler.py — 按变化轴组装配置

将 user、strategy、campaign 三层配置合并为完整配置字典。
campaign / strategy / user_profile / search_config 均从 SQLite 读取，
prompts / resume_template / resume_guide 保持 YAML 文件加载。
"""
import json
import os
import yaml

from config import emit, is_diagnose_mode

PROFILES_DIR = "profiles"


def _load_yaml(rel_path: str) -> dict:
    """加载 YAML 文件，不存在时返回空 dict。"""
    if not os.path.exists(rel_path):
        emit(f"[config_assembler] 文件不存在: {rel_path}")
        return {}
    with open(rel_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _validate_weight_profile(strategy_name: str, weight_profile: dict):
    """检查 weight_profile 五维度是否加起来等于 100。"""
    if not weight_profile:
        return
    total = sum(weight_profile.values())
    if total != 100:
        emit(f"[config_assembler] 警告: 策略 '{strategy_name}' 的 weight_profile 总和为 {total}，不为 100")
    else:
        if is_diagnose_mode(): emit(f"[config_assembler] 策略 '{strategy_name}' weight_profile 总和验证通过 (100)")


def load_campaign(campaign_name: str, user_id: int = None) -> dict:
    """
    加载一个 campaign，返回合并后的完整配置字典。

    流程：
    1. 从 SQLite campaigns 表读取 campaign
    2. 从 SQLite user_profiles 表读取当前活跃用户画像
    3. 从 SQLite strategies 表读取对应策略
    4. 从 SQLite search_config 表读取通用配置
    5. 从 YAML 文件读取 prompts、resume_template、resume_guide
    6. 按优先级合并：通用配置 → 策略配置 → campaign 顶层字段
    """
    # ── 1. 加载 campaign ──
    from config import _db_fetch_one
    if user_id is not None:
        row = _db_fetch_one(
            "SELECT data FROM campaigns WHERE name = ? AND owner_id = ?",
            (campaign_name, user_id)
        )
    else:
        row = _db_fetch_one("SELECT data FROM campaigns WHERE name = ?", (campaign_name,))
    if not row:
        raise FileNotFoundError(f"Campaign 不存在: {campaign_name}")
    campaign = json.loads(row["data"])

    # ── 4. 加载系统配置（search_config.yaml 中的系统基础设施部分）──
    from config import load_search_config_dict
    search_cfg, _ = load_search_config_dict()
    if not search_cfg:
        search_cfg = {}
    # user 从 profiles/.current_user 读取
    from config import get_current_user
    user_name = get_current_user()
    strategy_name = campaign.get("strategy", "")
    if not strategy_name:
        raise ValueError(f"Campaign '{campaign_name}' 缺少 strategy 字段")

    if is_diagnose_mode():
        emit(f"[config_assembler] 加载 campaign: {campaign_name}")
        emit(f"  user: {user_name}")
        emit(f"  strategy: {strategy_name}")

    # ── 2. 加载用户画像 ──
    row = _db_fetch_one("SELECT data FROM user_profiles WHERE is_current = 1")
    if row:
        user_profile = json.loads(row["data"])
    else:
        user_profile = {}
        emit(f"[config_assembler] 警告: 用户画像为空或不存在")

    # ── 3. 加载策略（全部用户策略 + campaign 选中的策略）──
    from config import _db_fetch_all

    # 3a. 加载用户的全部策略（构建完整 weight_profiles / weight_rules）
    all_rows = _db_fetch_all(
        "SELECT name, data FROM strategies WHERE owner_id = ? ORDER BY id",
        (user_id,)
    )
    if not all_rows:
        # 回退：user_id 为 None (CLI 模式) 或用户没有策略时，使用全局策略
        all_rows = _db_fetch_all(
            "SELECT name, data FROM strategies WHERE owner_id IS NOT NULL ORDER BY id LIMIT 20"
        )

    weight_profiles = {}
    weight_rules = {}
    for r in all_rows:
        s = json.loads(r["data"])
        weight_profiles[r["name"]] = s.get("weight_profile", {})
        weight_rules[r["name"]] = s.get("weight_rules_keywords", [])

    # 3b. 单独加载 campaign 选中的策略（用于 min_match_score 等参数）
    row = _db_fetch_one(
        "SELECT data FROM strategies WHERE name = ? AND owner_id = ? LIMIT 1",
        (strategy_name, user_id if user_id else 1)
    )
    if not row:
        raise FileNotFoundError(f"策略不存在: {strategy_name}")
    strategy = json.loads(row["data"])

    # 校验 weight_profile
    wp = strategy.get("weight_profile", {})
    if wp:
        _validate_weight_profile(strategy_name, wp)

    # ── 4. 构建 base_config（复用已加载的 search_cfg）──
    base_config = {
        "llm": search_cfg.get("llm", {}),
        "filters": search_cfg.get("filters", {}),
        "market_analysis": search_cfg.get("market_analysis", {}),
        "sort_mode": search_cfg.get("sort_mode", "date"),
    }

    # ── 5. 加载 prompts 和简历配置 ──
    prompts = _load_yaml(os.path.join(PROFILES_DIR, "prompts.yaml"))
    resume_template = _load_yaml(os.path.join(PROFILES_DIR, "resume_template.yaml"))
    resume_guide = _load_yaml(os.path.join(PROFILES_DIR, "resume_guide.yaml"))

    # ── 6. 构建 matching 段（全部策略的 weight_profiles/weight_rules + 选中策略的参数）──
    sc_matching = search_cfg.get("matching", {})
    matching = {
        "weight_profiles": weight_profiles,
        "weight_rules": weight_rules,
        "min_match_score": strategy.get("min_match_score", 45),
        "top_n": strategy.get("top_n", 999),
        "borderline_rescore": strategy.get("borderline_rescore", True),
        "borderline_range": strategy.get("borderline_range", 8),
        "direction_batch_size": sc_matching.get("direction_batch_size", 20),
        "score_batch_size": sc_matching.get("score_batch_size", 5),
        "rescore_batch_size": sc_matching.get("rescore_batch_size", 5),
    }

    # ── 7. 组装基础配置 ──
    config = {
        "user_profile": user_profile,
        "strategy": strategy,
        "strategy_name": strategy_name,
        "search_queries": campaign.get("search_queries", []),
        "sort_mode": base_config["sort_mode"],
        "llm": base_config["llm"],
        "filters": base_config["filters"],
        "max_pages_per_query": search_cfg.get("search", {}).get("max_pages", 3),
        "max_pages_limit": search_cfg.get("search", {}).get("max_pages_limit", 50),
        "max_total_results": search_cfg.get("search", {}).get("max_total_results", 200),
        "search": search_cfg.get("search", {}),
        "resume_gen": search_cfg.get("resume_gen", {}),
        "matching": matching,
        "market_analysis": base_config["market_analysis"],
        "prompts": prompts,
        "resume_template": resume_template,
        "resume_guide": resume_guide,
    }

    if is_diagnose_mode(): emit(f"  配置组装完成")
    return config


# ── 快速验证 ──
if __name__ == "__main__":
    import json
    config = load_campaign("web3_hunt")

    # 基本断言
    assert "user_profile" in config, "缺少 user_profile"
    wp = config.get("strategy", {}).get("weight_profile", {})
    assert wp.get("industry") == 30, f"web3 industry 权重应为 30，实际为 {wp.get('industry')}"
    assert len(config.get("search_queries", [])) == 3, "search_queries 应包含 3 组关键词"

    print()
    print("=" * 50)
    print("验证通过")
    print()
    print(f"  user_profile: {'已加载' if config.get('user_profile') else '空'}")
    wp = config["strategy"]["weight_profile"]
    print(f"  weight_profile: {wp}")
    print(f"  weight_profile 总和: {sum(wp.values())}")
    print(f"  search_queries: {len(config['search_queries'])} 组")
    print(f"  sort_mode: {config['sort_mode']}")
    print(f"  llm provider: {config['llm'].get('provider', 'N/A')}")
    print(f"  llm model: {config['llm'].get('model', 'N/A')}")
