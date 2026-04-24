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
- company_full_name: **投标公司**全称。注意:投标方是 docx 正文中"投标人（盖章）：" 后紧跟的公司全名;
  不是文件里反复出现的招标方/项目名/项目甲方(例如"锂源(江苏)科技有限公司"这类项目名不要填)
- company_short_name: 公司简称(投标方)
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
给定一个 XLSX 文件的**所有候选价格表 sheet** 的前 5~8 行预览,输出 sheets_config 数组。

每个候选 sheet 返回一项:
- sheet_name: 原样
- header_row: 表头所在行号(1-based,即实际 Excel 行号)
- column_mapping: 6 列映射(编码 / 名称 / 单位 / 数量 / 单价 / 合价) → Excel 列字母(A/B/C...)
  - 某列不存在 → null
  - skip_cols 列出需跳过的列(如汇总行、长说明列)

**重要:候选 sheet 甄别规则**
- **包含**:sheet 有表头 + 至少 1 行真实数值数据 的价格表(如"报价表"/"监理人员报价单分析表"/"工程量清单")
- **排除**:以下类型的 sheet 即使出现在文件里也**不要**放进 sheets_config:
  - 人员进场计划 / 附件说明 / 目录 / 封面
  - 空表、只有表头无数据的表
  - 纯文字说明(备注、条款)
- 同 xlsx 多个价格表 sheet(主报价表 + 明细分析表)→ 各自独立返回,column_mapping 可不同

输出 JSON 对象(不要 markdown 代码块):
{
  "sheets_config": [
    {
      "sheet_name": "报价表",
      "header_row": 3,
      "column_mapping": {
        "code_col": "A" | null,
        "name_col": "B" | null,
        "unit_col": "D" | null,
        "qty_col": "E" | null,
        "unit_price_col": "F" | null,
        "total_price_col": "G" | null,
        "skip_cols": ["C", "H"]
      }
    },
    ...可能有更多候选 sheet...
  ]
}
"""

PRICE_RULE_USER_TEMPLATE = """XLSX 的所有 sheet 预览(每个 sheet 最多前 {preview_rows} 行):

{sheets_block}

请返回 sheets_config 数组,只包含**真实价格表 sheet**(跳过人员进场计划/附件/目录等)。"""


__all__ = [
    "ROLE_CLASSIFY_SYSTEM_PROMPT",
    "ROLE_CLASSIFY_USER_TEMPLATE",
    "PRICE_RULE_SYSTEM_PROMPT",
    "PRICE_RULE_USER_TEMPLATE",
]
