## ADDED Requirements

### Requirement: role_classifier 诊断日志契约

`backend/app/services/parser/llm/role_classifier.py::_classify_bidder_inner` SHALL 在 LLM 调用前后输出足够诊断 N3(LLM 大文档精度退化)根因归类的结构化日志,覆盖"LLM 成功 + 自返 low" 与 "JSON 解析失败"两条现有 `kind` 日志未覆盖的决策路径。具体内容:

- **input shape**:`logger.info` SHALL 在 `llm.complete()` 调用前记录 `files=<int>`、`snippet_empty=<int>`(文档首段正文为空的份数)、`total_prompt_chars=<int>`(完整 user message 字符数)、`file_name_has_mojibake=<bool>`(文件名是否疑似 cp850→GBK 乱码,启发式判定)
- **output confidence mix**:`logger.info` SHALL 在 LLM 返回解析成功后、roles 写入 DB 前记录 `llm_confidence_high=<int>`、`llm_confidence_low=<int>`、`llm_confidence_missing=<int>`(LLM 漏返而走关键词兜底的文档数);三者之和 MUST 等于该 bidder 该批次文档数
- **raw text head**:既有 "role_classifier LLM returned invalid JSON" `logger.warning` SHALL 追加 `raw_text_head=<前 200 字符>`(按字符数,不是字节),用于诊断 response 截断模式

上述三处日志 MUST 零控制流/返回值变化,失败仅影响日志输出不影响主流水线。LLM 调用失败路径(既有 `kind=X msg=Y` warning)保持不变;日志 level 用 `logger.info`(prod 默认 warning 级不输出,诊断时主动调低)。

#### Scenario: LLM 成功路径记 input shape + output mix
- **WHEN** role_classifier 处理一个 bidder,其 DOCX/XLSX 文档集传入 LLM 并返回有效 JSON(含 high / low / 漏返文档的混合)
- **THEN** caplog 捕获 1 条 input shape info(files/snippet_empty/total_prompt_chars/file_name_has_mojibake 字段齐全)+ 1 条 output mix info(high+low+missing 之和等于输入文档数);**不**触发任何 kind warning 或 invalid JSON warning

#### Scenario: LLM 失败路径仅记 kind,不记 output mix
- **WHEN** role_classifier 处理一个 bidder,LLM 返回 `result.error != None`(kind=timeout / rate_limit / ...)
- **THEN** caplog 捕获既有 `"role_classifier LLM error kind=%s msg=%s; fallback to keywords"` warning(未回归)+ input shape info(调用前已打);**不**捕获 output confidence mix info(因为 LLM 未成功返回,不存在 mix 状态)

#### Scenario: JSON 解析失败路径 warning 带 raw_text_head
- **WHEN** LLM 返回非 None、但 `_parse_llm_json` 返回 None(LLM 输出为非法 JSON,如被截断或 markdown 包裹错位)
- **THEN** caplog 捕获的 warning 消息 MUST 含 `raw_text_head=` 字段 + 前 200 字符原始输出;**不**触发 output confidence mix info(解析未成功)
