"""全局检测规则默认配置 (C17 admin-users)

requirements.md §8 SystemConfig.config 字段默认值。
这是"恢复默认"的唯一真相源。
"""

from __future__ import annotations

DEFAULT_RULES_CONFIG: dict = {
    "dimensions": {
        "hardware_fingerprint": {
            "enabled": True,
            "weight": 20,
            "llm_enabled": True,
        },
        "error_consistency": {
            "enabled": True,
            "weight": 20,
            "llm_enabled": True,
        },
        "text_similarity": {
            "enabled": True,
            "weight": 15,
            "llm_enabled": True,
            "threshold": 85,
        },
        "price_similarity": {
            "enabled": True,
            "weight": 15,
            "llm_enabled": True,
            "threshold": 95,
        },
        "image_reuse": {
            "enabled": True,
            "weight": 13,
            "llm_enabled": True,
            "phash_distance": 5,
        },
        "language_style": {
            "enabled": True,
            "weight": 10,
            "llm_enabled": True,
            "group_threshold": 20,
        },
        "software_metadata": {"enabled": True, "weight": 7},
        "pricing_pattern": {
            "enabled": True,
            "r_squared_threshold": 0.95,
        },
        "price_ceiling": {
            "enabled": True,
            "variance_threshold": 0.02,
            "range_min": 0.98,
            "range_max": 1.00,
        },
        "operation_time": {
            "enabled": True,
            "window_minutes": 30,
            "min_bidders": 3,
        },
    },
    "risk_levels": {"high": 70, "medium": 40},
    "doc_role_keywords": {
        "technical": ["技术方案", "技术标", "技术建议书"],
        "construction": ["施工组织", "施工方案", "施工设计"],
        "pricing": ["报价", "清单", "工程量", "商务标", "投标报价"],
        "unit_price": ["综合单价", "单价分析"],
        "bid_letter": ["投标函", "投标书"],
        "qualification": ["资质", "资格", "营业执照"],
        "company_intro": ["企业介绍", "公司简介", "公司概况"],
        "authorization": ["授权", "委托"],
    },
    "hardware_keywords": ["加密锁号", "MAC地址", "序列号", "硬盘序列号", "主板", "CPU"],
    "metadata_whitelist": ["Administrator", "User", "Admin", "Microsoft Office User"],
    "min_paragraph_length": 50,
    "file_retention_days": 90,
    # admin-llm-config:LLM 运行期配置。DB 无此段时代码回退 env + 默认值。
    "llm": {
        "provider": "dashscope",
        "api_key": "",
        "model": "qwen-plus",
        "base_url": None,
        "timeout_s": 30,
    },
}
