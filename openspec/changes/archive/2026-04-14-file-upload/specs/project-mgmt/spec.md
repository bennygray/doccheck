## MODIFIED Requirements

### Requirement: 为 C4+ 预留的占位字段

项目详情响应 MUST 包含 `bidders / files / progress` 三个字段。C4 起:

- `bidders` 字段返回真实投标人摘要列表(每项含 `id / name / parse_status / file_count`),来自 `bidders` 表的未软删记录
- `files` 字段返回该项目下所有投标人的 `bid_documents` 扁平列表摘要(每项含 `id / bidder_id / file_name / file_type / parse_status`),仅包含未被删除的记录
- `progress` 字段返回项目级汇总:`{"total_bidders": int, "pending_count": int, "extracting_count": int, "extracted_count": int, "failed_count": int, "needs_password_count": int}`;项目无投标人时所有计数为 0

列表响应(`GET /api/projects/`)的 `risk_level` 字段在 C6 检测上线前仍恒为 null,**此字段约束保持不变**。

#### Scenario: 详情返回真实 bidders 摘要

- **WHEN** reviewer 请求自己项目的详情,且该项目已有 2 个投标人
- **THEN** 响应 body 的 `bidders` 字段为长度 2 的数组,每项含 `id / name / parse_status / file_count`;`files` 为对应扁平文件摘要;`progress.total_bidders=2`

#### Scenario: 空项目详情返回空数组与零进度

- **WHEN** reviewer 请求自己项目(未添加投标人)的详情
- **THEN** `bidders=[]`,`files=[]`,`progress.total_bidders=0` 且其他计数均为 0

#### Scenario: 列表响应含 risk_level

- **WHEN** 请求列表
- **THEN** 每条 `items[i]` 均含 `risk_level` 字段(C4 阶段仍恒为 null)
