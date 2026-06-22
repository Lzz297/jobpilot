"""
config_assembler.py — 按变化轴组装配置

将 user、strategy、campaign 三层配置合并为完整配置字典。
旧路径（profiles/me.yaml + search_config.yaml）保持不动，新旧模式并行。
"""
import os
import yaml
import json

PROFILES_DIR = "profiles"


def _load_yaml(rel_path: str) -> dict:
    """加载 YAML 文件，不存在时返回空 dict。"""
    if not os.path.exists(rel_path):
        print(f"[config_assembler] 文件不存在: {rel_path}")
        return {}
    with open(rel_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _validate_weight_profile(strategy_name: str, weight_profile: dict):
    """检查 weight_profile 五维度是否加起来等于 100。"""
    if not weight_profile:
        return
    total = sum(weight_profile.values())
    if total != 100:
        print(f"[config_assembler] 警告: 策略 '{strategy_name}' 的 weight_profile 总和为 {total}，不为 100")
    else:
        print(f"[config_assembler] 策略 '{strategy_name}' weight_profile 总和验证通过 (100)")


def load_campaign(campaign_name: str) -> dict:
    """
    加载一个 campaign，返回合并后的完整配置字典。

    流程：
    1. 读取 instances/campaigns/{campaign_name}.yaml
    2. 获取 user 和 strategy 的值
    3. 读取 instances/users/{user}.yaml 作为用户画像
    4. 读取 instances/strategies/{strategy}.yaml 作为策略
    5. 读取 search_config.yaml 获取通用配置
    6. 读取 prompts.yaml、resume_guide.yaml、resume_template.yaml
    7. 按优先级合并：通用配置（search_config.yaml）→ 策略配置（strategy 文件）→ campaign 顶层字段（无 overrides）
    """
    # ── 1. 加载 campaign ──
    from config import _db_fetch_one
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

    print(f"[config_assembler] 加载 campaign: {campaign_name}")
    print(f"  user: {user_name}")
    print(f"  strategy: {strategy_name}")

    # ── 2. 加载用户画像 ──
    row = _db_fetch_one("SELECT data FROM user_profiles WHERE is_current = 1")
    if row:
        user_profile = json.loads(row["data"])
    else:
        user_profile = {}
        print(f"[config_assembler] 警告: 用户画像为空或不存在")

    # ── 3. 加载策略 ──
    row = _db_fetch_one("SELECT data FROM strategies WHERE name = ?", (strategy_name,))
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

    # ── 6. 构建 matching 段（从 strategy 文件 + 策略通用参数）──
    matching = {
        "weight_profiles": {strategy_name: strategy.get("weight_profile", {})},
        "weight_rules": {strategy_name: strategy.get("weight_rules_keywords", [])},
        "min_match_score": strategy.get("min_match_score", 45),
        "top_n": strategy.get("top_n", 999),
        "borderline_rescore": strategy.get("borderline_rescore", True),
        "borderline_range": strategy.get("borderline_range", 8),
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
        "max_total_results": search_cfg.get("search", {}).get("max_total_results", 200),
        "search": search_cfg.get("search", {}),
        "resume_gen": search_cfg.get("resume_gen", {}),
        "matching": matching,
        "market_analysis": base_config["market_analysis"],
        "prompts": prompts,
        "resume_template": resume_template,
        "resume_guide": resume_guide,
    }

    print(f"  配置组装完成")
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
