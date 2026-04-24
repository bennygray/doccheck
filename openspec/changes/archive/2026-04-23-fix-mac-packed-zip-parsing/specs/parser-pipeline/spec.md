## MODIFIED Requirements

### Requirement: LLM 角色分类与身份信息提取

系统 SHALL 对每个 `extracted` 的 bidder 执行 **一次 LLM 调用** 完成两项任务:9 种角色分类 + 投标人身份信息提取。输入为该 bidder 所有 DOCX/XLSX 文件的 `(file_name, first_500_chars_of_body_text)` 列表;输出为 `{roles: [{document_id, role, confidence}], identity_info: {...}}`。

- **角色枚举**(9 种):`technical / construction / pricing / unit_price / bid_letter / qualification / company_intro / authorization / other`
- **身份信息** JSONB schema:`{company_full_name?, company_short_name?, project_manager?, legal_rep?, qualification_no?, contact_phone?}`,所有字段可选
- **LLM 失败兜底**(D2 决策 + fix-mac-packed-zip-parsing 补丁):
  - 角色分类:两级兜底链路
    1. 先对 `parse_status=identified` 的 DOCX/XLSX 读取 `document_texts` 首段 ≤1000 字(按 `paragraph_index` 升序取 `location='body'` 最早的段落),调 `classify_by_keywords_on_text` 做子串关键词匹配(复用 `ROLE_KEYWORDS`);命中即返回对应角色,`role_confidence='low'`
    2. 未命中(或该文档正文为空/未 identified)再落到 `classify_by_keywords(doc.file_name)` 文件名兜底;仍未命中则 `role='other', role_confidence='low'`
  - 身份信息:不做规则兜底,`bidders.identity_info = NULL`;bidder 仍进 `identified`(身份缺失不阻塞)
- 结果写 `bid_documents.file_role` / `bid_documents.role_confidence` / `bidders.identity_info`

#### Scenario: 正常 LLM 成功分类

- **WHEN** 一个 bidder 有 5 个 DOCX(含"技术方案.docx"/"投标报价.xlsx"等),LLM 返回有效 JSON
- **THEN** 5 个文档各得一个 `file_role` 值;`bidders.identity_info` 非 NULL;bidder.parse_status = `identified`;SSE 推 `document_role_classified` × 5 + `bidder_status_changed` 事件

#### Scenario: LLM 超时走规则兜底

- **WHEN** 调用 LLM 返回 `LLMResult.error.kind='timeout'`
- **THEN** 所有文档先走正文关键词兜底、未命中再走文件名关键词兜底;命中任一路径 → 对应角色 + `role_confidence='low'`;全未命中 → `role='other', role_confidence='low'`;`bidders.identity_info = NULL`;bidder 进 `identified`

#### Scenario: LLM 返回非法 JSON 走规则兜底

- **WHEN** LLM 返回 `text='{"roles": [...' 缺右括号
- **THEN** 视同 `bad_response` 错,走两级兜底路径(同 timeout 场景)

#### Scenario: 文件名乱码但正文含关键词

- **WHEN** LLM 失败且文件名为乱码(如 `Σ╛¢σ║öσòåA/...docx`,文件名关键词零命中),但正文首段含"投标报价一览表"字样
- **THEN** 正文关键词匹配命中 `pricing`,`file_role='pricing', role_confidence='low'`;不再走文件名兜底

#### Scenario: 身份信息部分字段缺失

- **WHEN** LLM 返回 `identity_info={"company_full_name": "某某有限公司"}` 其他字段未返回
- **THEN** `bidders.identity_info={"company_full_name": "某某有限公司"}`;缺失字段不写入 NULL key(节省存储)

#### Scenario: 低置信度文档标"待确认"

- **WHEN** LLM 返回 `{document_id: 7, role: "technical", confidence: "low"}`
- **THEN** `bid_documents.role_confidence='low'`;前端 API 响应中 `role_confidence` 字段为 `'low'`(前端用于黄色徽章渲染)

#### Scenario: 规则兜底命中"other"

- **WHEN** 文件名与正文均不含任何关键词,LLM 也失败
- **THEN** `file_role='other', role_confidence='low'`

#### Scenario: 文档未 identified 时跳过正文兜底

- **WHEN** LLM 失败,且某文档 `parse_status != 'identified'`(内容提取失败,`document_texts` 为空)
- **THEN** 跳过正文关键词兜底,直接走文件名关键词兜底

---

### Requirement: 角色关键词兜底规则

系统 SHALL 在 `app/services/parser/llm/role_keywords.py` 维护 `ROLE_KEYWORDS: dict[str, list[str]]` 常量,用于 LLM 失败时的"正文关键词兜底 + 文件名关键词兜底"两级匹配。

- 8 个角色各配一组关键词(pricing / technical / construction / unit_price / bid_letter / qualification / company_intro / authorization);第 9 个角色 `other` 为默认兜底,无需关键词
- 提供两个入口函数:
  - `classify_by_keywords(file_name: str) -> str | None`:对文件名做子串包含匹配(不区分大小写),按字典声明顺序遍历,首次命中即返回,全未命中返回 `None`
  - `classify_by_keywords_on_text(text: str) -> str | None`:对正文首段文本做子串包含匹配(不区分大小写),规则同上
- 本期不支持管理员动态维护(D2 决策);C17 升级为 DB + admin UI

#### Scenario: 角色关键词常量存在

- **WHEN** 导入 `ROLE_KEYWORDS`
- **THEN** 字典含 8 个角色键,每个值为非空字符串列表

#### Scenario: 文件名命中关键词返回对应角色

- **WHEN** 文件名 "投标报价.xlsx",调用 `classify_by_keywords(name)`
- **THEN** 返回 `"pricing"`(命中关键词 "报价")

#### Scenario: 文件名未命中返回 None

- **WHEN** 文件名 "XYZ.docx" 不含任何关键词
- **THEN** `classify_by_keywords` 返回 `None`(调用方据此决定走下一层兜底或兜底到 "other")

#### Scenario: 正文命中关键词返回对应角色

- **WHEN** 正文首段"本公司针对本次招标项目提交投标报价一览表如下",调用 `classify_by_keywords_on_text(text)`
- **THEN** 返回 `"pricing"`(命中关键词 "报价")

#### Scenario: 正文未命中返回 None

- **WHEN** 正文首段不含任何角色关键词
- **THEN** `classify_by_keywords_on_text` 返回 `None`
