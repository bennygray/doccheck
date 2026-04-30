## ADDED Requirements

### Requirement: 招标文件 (tender) 上传 API

系统 SHALL 提供项目级招标文件上传接口,与投标人 (bidder) 上传解耦。

接口:`POST /api/projects/{pid}/tender`(multipart/form-data,字段 `file`)。

文件大小限制 MUST = 500MB(与 BidDocument 上传一致)。

支持格式 MUST = `.docx` / `.xlsx` / `.zip`(zip 内部走现有解压管道,自动展开 docx/xlsx;**本期不支持** PDF 扫描件,文档 doc legacy 不在此 change 范围)。

上传成功后系统 MUST:
1. 写 `TenderDocument` 行(parse_status='pending')
2. 调用 `_persist_archive` 落盘到 `<upload_dir>/<pid>/tender/<md5_prefix>_<safe_name>`
3. 触发异步 parser(复用现有 `trigger_extract`),固定 `file_role='tender'`(在 parse 上下文,**不**写入 BidDocument)
4. 返回 `TenderDocument.id` + `parse_status='pending'`

#### Scenario: 上传 docx 招标文件成功

- **WHEN** 用户对项目 P 上传 50KB 的 .docx 文件
- **THEN** 系统返回 201,TenderDocument 行 parse_status='pending';异步 parser 启动后转 'extracted' 或 'failed'

#### Scenario: 上传 zip 招标文件包

- **WHEN** 用户上传含 4 文件 (3 docx + 1 xlsx) 的招标文件 zip
- **THEN** 系统解压并入库 4 行 DocumentText/DocumentSheet 关联到 TenderDocument

#### Scenario: 文件超大小限制

- **WHEN** 用户上传 600MB 文件
- **THEN** 系统返回 413,不写 TenderDocument 行

#### Scenario: 不支持的 PDF 扫描件

- **WHEN** 用户上传 .pdf 招标文件
- **THEN** 系统返回 415,提示"本期不支持 PDF 招标文件,留 follow-up"

---

### Requirement: 招标文件列表与删除 API

接口:
- `GET /api/projects/{pid}/tender` 返回项目下所有未软删的 TenderDocument
- `DELETE /api/projects/{pid}/tender/{tid}` 软删除指定招标文件

软删除后该 tender 的 segment_hash MUST NOT 再参与 baseline_resolver 计算。

删除后系统 MUST NOT 自动触发重检;用户可手动启动新检测以反映 baseline 变化。

#### Scenario: 列表返回未软删的招标文件

- **WHEN** 项目 P 含 2 份 tender,其中 1 份 deleted_at != NULL
- **THEN** GET 返回 1 份 (未软删的)

#### Scenario: 软删除后 baseline_resolver 不读

- **WHEN** 删除 tender T,启动新检测
- **THEN** baseline_resolver 加载的 tender hash 集合 MUST NOT 含 T 的段 hash

---

### Requirement: tender 解析失败 fail-soft

TenderDocument 解析失败(`parse_status='failed'`) MUST NOT 阻塞 detector 运行。

baseline_resolver MUST 跳过 parse_status != 'extracted' 的 tender,降级走 consensus 或警示路径。

UI 项目详情页 SHALL 在该 tender 卡上显示降级提示(如"招标文件解析失败,本次检测降级为共识/警示模式")。

#### Scenario: tender 解析失败不阻塞 detector

- **WHEN** project 有 2 份 tender,1 份 extracted、1 份 failed,启动检测
- **THEN** baseline_resolver MUST 仅用 extracted 的 hash 集合;detector 正常完成

#### Scenario: 全部 tender 失败降级共识

- **WHEN** project 有 1 份 tender 且 parse_status='failed',投标方 4 家
- **THEN** baseline 走 consensus 路径(L2),baseline_source ∈ {'consensus', 'none'}

#### Scenario: tender extracted 但 hash 集合为空降级 L2

- **WHEN** project 有 1 份 tender 且 parse_status='extracted',但解析后 segment_hash 集合为空(如纯图片 docx 无文本段)
- **THEN** baseline_resolver MUST 视同无可用 tender,降级到 L2 共识路径(N≥3 时)或 L3 警示(N≤2 时)

#### Scenario: tender 软删后老 evidence 不加 stale 标注

- **WHEN** project v=1 检测时含 1 份 tender,evidence baseline_source='tender';用户随后软删该 tender
- **THEN** v=1 evidence MUST 保留只读不变(baseline_source='tender' 仍体现历史事实);UI MUST NOT 给 v=1 加 stale 标注(用户责任,不主动反向 backfill)
