"""LLM Prompt 常量 (C5 parser-pipeline)

4 个 Prompt:
- ROLE_CLASSIFY_*: 角色分类 + 投标人身份信息提取(一次 LLM 调用完成 US-4.3 两个任务)
- PRICE_RULE_*: 报价表结构识别(sheet_name / header_row / column_mapping)

Prompt 正文可在实施期调优(不进 spec)。

**honest-detection-results N2 同步提醒**:
role 描述里的关键词举例与 ``role_keywords.py::ROLE_KEYWORDS`` 存在语义耦合。
更新本 prompt 时 MUST 同步 review `role_keywords.py`(SSOT)和 `admin/rules_defaults.py`
三处是否一致;测试 `test_role_keywords_2way_sync.py` 只机械校验后两处的 key/value
非空,prompts.py 靠人工 review 维护(自然语言描述无可靠关键词提取规则)。
"""

from __future__ import annotations

ROLE_CLASSIFY_SYSTEM_PROMPT = """你是一个招投标文档分析助手。任务:
1. 为给定的投标人文件列表,按文件名与首段文本判定每个文件的角色标签(9 选 1)
2. 同时从所有文件内容中提取投标人的身份信息

角色标签枚举(必须从这 9 个中选):
- technical: 技术方案 / 技术标 / 技术建议书
- construction: 施工组织设计 / 施工方案 / 施工进度 / 进度计划
- pricing: 报价清单 / 工程量清单 / 商务标 / 投标报价 / 价格标 / 开标一览表
- unit_price: 综合单价分析表
- bid_letter: 投标函 / 投标书
- qualification: 资质证明 / 营业执照 / 资信标 / 资信 / 业绩 / 类似业绩
- company_intro: 企业介绍 / 企业简介 / 公司简介
- authorization: 授权委托书
- other: 以上均不匹配

身份信息字段(皆可选,缺失留空):
- company_full_name: 投标公司全称
- company_short_name: 公司简称
- project_manager: 项目经理姓名
- legal_rep: 法定代表人
- qualification_no: 资质编号
- contact_phone: 联系电话

输出 JSON 对象(不要 markdown 代码块,不要解释):
{
  "roles": [
    {"document_id": <int>, "role": "<enum>", "confidence": "high" | "low"}
  ],
  "identity_info": {
    "company_full_name": "<str or omit>",
    ...
  }
}
"""

ROLE_CLASSIFY_USER_TEMPLATE = """投标人文件列表(共 {file_count} 个):

{files_block}

请输出 JSON。"""


PRICE_RULE_SYSTEM_PROMPT = """你是一个 Excel 报价表结构识别助手。任务:
给定一个 XLSX 报价表的 sheet 名 + 前 5~8 行预览,判定:
- header_row: 表头所在行号(1-based,即实际 Excel 行号)
- column_mapping: 6 个必需列(编码 / 名称 / 单位 / 数量 / 单价 / 合价)各自对应的列字母(A/B/C...)

列字母使用 Excel 风格(A=第1列, B=第2列, ...)。
如果某列不存在于表中,对应字段设为 null。
skip_cols 列出需要跳过的列字母(如汇总行、说明列)。

输出 JSON 对象(不要 markdown 代码块):
{
  "sheet_name": "<原样输出>",
  "header_row": <int>,
  "column_mapping": {
    "code_col": "A" | null,
    "name_col": "B" | null,
    "unit_col": "C" | null,
    "qty_col": "D" | null,
    "unit_price_col": "E" | null,
    "total_price_col": "F" | null,
    "skip_cols": []
  }
}
"""

PRICE_RULE_USER_TEMPLATE = """Sheet 名: {sheet_name}

前 {preview_rows} 行预览:
{preview_block}

请输出 JSON。"""


__all__ = [
    "ROLE_CLASSIFY_SYSTEM_PROMPT",
    "ROLE_CLASSIFY_USER_TEMPLATE",
    "PRICE_RULE_SYSTEM_PROMPT",
    "PRICE_RULE_USER_TEMPLATE",
]
