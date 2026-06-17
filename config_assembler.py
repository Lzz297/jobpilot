"""
config_assembler.py — 按变化轴组装配置

将 user、strategy、campaign 三层配置合并为完整配置字典。
旧路径（profiles/me.yaml + search_config.yaml）保持不动，新旧模式并行。
"""
import os
import copy
import yaml

INSTANCES_DIR = "instances"
PROFILES_DIR = "profiles"


def _deep_merge(base: dict, override: dict) -> dict:
    """深度合并两个字典。override 中的值覆盖 base，嵌套字典逐层合并。"""
    result = copy.deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


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
    7. 按优先级合并：通用配置 → 策略配置 → campaign.overrides
    """
    # ── 1. 加载 campaign ──
    campaign_path = os.path.join(INSTANCES_DIR, "campaigns", f"{campaign_name}.yaml")
    campaign = _load_yaml(campaign_path)
    if not campaign:
        raise FileNotFoundError(f"Campaign 文件不存在: {campaign_path}")

    # ── 4. 加载系统配置（search_config.yaml 中的系统基础设施部分）──
    search_cfg = _load_yaml(os.path.join(PROFILES_DIR, "search_config.yaml"))
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
    user_path = os.path.join(INSTANCES_DIR, "users", f"{user_name}.yaml")
    user_profile = _load_yaml(user_path)
    if not user_profile:
        print(f"[config_assembler] 警告: 用户画像为空或不存在: {user_path}")

    # ── 3. 加载策略 ──
    strategy_path = os.path.join(INSTANCES_DIR, "strategies", f"{strategy_name}.yaml")
    strategy = _load_yaml(strategy_path)
    if not strategy:
        raise FileNotFoundError(f"策略文件不存在: {strategy_path}")

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
        "sort_mode": campaign.get("sort_mode", base_config["sort_mode"]),
        "llm": base_config["llm"],
        "filters": base_config["filters"],
        "max_pages_per_query": campaign.get("overrides", {}).get("max_pages_per_query", 3),
        "max_total_results": campaign.get("overrides", {}).get("max_total_results", 200),
        "matching": matching,
        "market_analysis": base_config["market_analysis"],
        "prompts": prompts,
        "resume_template": resume_template,
        "resume_guide": resume_guide,
    }

    # ── 8. 应用 campaign overrides ──
    overrides = campaign.get("overrides", {})
    if overrides:
        config = _deep_merge(config, overrides)
        print(f"  已应用 overrides: {list(overrides.keys())}")

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
