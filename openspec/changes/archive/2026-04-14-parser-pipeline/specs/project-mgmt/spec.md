## MODIFIED Requirements

### Requirement: 为 C4+ 预留的占位字段

项目详情响应 MUST 包含 `bidders / files / progress` 三个字段。C5 起扩展 `progress` 字段的结构以覆盖解析流水线的阶段计数:

- `bidders` 字段返回真实投标人摘要列表(每项含 `id / name / parse_status / file_count`),来自 `bidders` 表的未软删记录(C4 语义保持)
- `files` 字段返回该项目下所有投标人的 `bid_documents` 扁平列表摘要(每项含 `id / bidder_id / file_name / file_type / parse_status / file_role / role_confidence`);**`file_role / role_confidence` 为 C5 新增字段**(C4 阶段恒 NULL,C5 由 LLM 填充)
- `progress` 字段返回项目级汇总,**C5 扩展为**:
  ```json
  {
    "total_bidders": int,
    "pending_count": int,
    "extracting_count": int,
    "extracted_count": int,
    "identifying_count": int,
    "identified_count": int,
    "pricing_count": int,
    "priced_count": int,
    "failed_count": int,
    "needs_password_count": int,
    "partial_count": int
  }
  ```
  `failed_count` 聚合所有失败态(`failed / identify_failed / price_failed`);`partial_count` 聚合 `partial / price_partial`。项目无投标人时所有计数为 0。

列表响应(`GET /api/projects/`)的 `risk_level` 字段在 C6 检测上线前仍恒为 null,**此字段约束保持不变**。

#### Scenario: 详情返回真实 bidders 摘要

- **WHEN** reviewer `GET /api/projects/{id}`,该项目含 2 个 bidder
- **THEN** 响应 200,body 中 `bidders` 为 2 项数组,每项含 `id / name / parse_status / file_count`

#### Scenario: 详情返回扁平 files 列表含 file_role

- **WHEN** reviewer `GET /api/projects/{id}`,该项目含 2 个 bidder 每个有 3 个 bid_document,其中首位 bidder 已 identified
- **THEN** 响应 body 中 `files` 为 6 项数组,每项含 `id / bidder_id / file_name / file_type / parse_status / file_role / role_confidence`;已 identified 的 bidder 的文档 `file_role` 非 NULL,其他文档 `file_role` 为 NULL

#### Scenario: progress 含 C5 新增计数

- **WHEN** 项目含 3 个 bidder(状态分别为 extracted / identifying / priced),1 个 bidder 为 price_partial
- **THEN** `progress` 的相应字段:`extracted_count=1, identifying_count=1, priced_count=1, partial_count=1`;`total_bidders=4`

#### Scenario: 空项目 progress 全零

- **WHEN** 项目尚无投标人
- **THEN** `progress` 各计数字段均为 0;`total_bidders=0`

#### Scenario: 列表 risk_level 仍 null

- **WHEN** `GET /api/projects/`(列表端点)
- **THEN** body 内每项 `risk_level` 字段为 null(C5 不改变此约束)
