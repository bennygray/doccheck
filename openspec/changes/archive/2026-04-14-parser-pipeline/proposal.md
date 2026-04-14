## Why

C4 完成后,压缩包解压落盘到 `extracted/<pid>/<bid>/<hash>/`,但 `bid_documents.file_role` / `bidders.identity_info` / `price_parsing_rules.column_mapping` 三处字段都是 NULL,系统停在"有文件名没内容"状态。C5 把**内容提取(DOCX/XLSX 读文本+元数据+图片)→ LLM 角色分类与身份信息提取 → LLM 报价表结构识别 → 报价数据回填**的解析流水线整条打通,完成 M2 定义的"上传压缩包 → 自动解析 → 看到投标人+文件角色+报价"端到端。M2 进度 3/3。

本次 propose 阶段已与用户敲定 5 项关键边界(详见 design.md):

- **A1 整体做**:不拆 C5a/C5b,接受 ~14 Requirement / ~45 Scenario(与 C4 同风格)
- **B1 完整 SSE 事件流**:改造 C1 `/demo/sse` 骨架为 `/api/projects/{pid}/parse-progress`,推送 `bidder_content_extracted / bidder_role_identified / project_price_rule_ready / bidder_priced / error` 等事件
- **C2 + β**:LLM 识别报价规则后**自动 `confirmed=true` 并立即批量回填**,用户事后可修正;bidder 所有 sheet 回填成功才进 `priced`,部分失败 → `price_partial`
- **报价维度可选**:无报价表的 bidder 终态 = `identified`,不必进 `priced`
- **D2 人工修正 a+b 做 c 降级**:前端完整做"改文档角色"+"改列映射";角色关键词兜底规则本期写 Python 常量,管理员后台维护留 C17
- **E3 DB 原子占位**:报价规则"项目级仅一次识别"用 `price_parsing_rules` 唯一约束 + `asyncio.Event` 快路径 + DB poll 慢路径实现;多 bidder 并发时 DB 负责并发控制,顺手消化 C4 留下的"event loop 重启丢任务"一半风险

## What Changes

### 数据模型(4 张新表 + 约束补强 + 枚举扩展 + alembic 0004)

- **`document_texts`**:`id / bid_document_id FK / paragraph_index / text TEXT / location (body|header|footer|textbox|table_row) / created_at`;支持 US-4.2 的段落级提取 + 页眉页脚分离
- **`document_metadata`**:`bid_document_id PK+FK(1:1) / author / last_saved_by / company / created_at / modified_at / app_name / app_version`
- **`document_images`**:`id / bid_document_id FK / file_path / md5 CHAR(32) / phash CHAR(64) / width / height / position`
- **`price_items`**:`id / bidder_id FK / price_parsing_rule_id FK / sheet_name / row_index / item_code / item_name / unit / quantity Numeric(18,4) / unit_price Numeric(18,2) / total_price Numeric(18,2) / created_at`
- **`price_parsing_rules` 约束补强**:新增 `status` 字段(`identifying | confirmed | failed`);新增 `UNIQUE(project_id) WHERE status IN ('identifying','confirmed')` 支撑 E3 原子占位
- **`bidders.parse_status` 枚举扩展**:新增 7 态 `identifying / identified / identify_failed / pricing / priced / price_partial / price_failed`
- **`bid_documents.parse_status` 枚举扩展**:新增 3 态 `identifying / identified / identify_failed`(文档级不进 priced,只有 bidder 级有)

### 后端端点(4 个新 + 1 个补齐)

- `PATCH /api/documents/{id}/role` {role}:修改文档角色(US-4.3 AC-4~5)
- `GET /api/projects/{pid}/parse-progress`(SSE 长连接):完整事件流(B1 决策)
- `POST /api/documents/{id}/re-parse`:失败文件重试(US-4.2 AC-7 + execution-plan §3 C5 验证场景 5)
- `GET /api/projects/{pid}/bidders/{bid}/price-items`:返回该投标人回填完成的 PriceItem 列表(前端详情页展示用)
- `PUT /api/projects/{pid}/price-rules/{id}`:C4 骨架 → C5 闭环(修正后触发批量重回填;C4 PUT 仅写 DB 不触发回填)

### 后端服务(3 个新子模块)

- **`app/services/parser/content/`**:
  - `docx_parser.py`(python-docx 读正文/页眉页脚/文本框/表格)
  - `xlsx_parser.py`(openpyxl 读所有 sheet 原始数据,含隐藏 sheet / 合并单元格展开)
  - `image_parser.py`(Pillow + imagehash 计算 MD5 / pHash)
  - `metadata_parser.py`(core.xml / app.xml / docProps)
  - 入口函数 `extract_content(bid_document_id)` 按 file_type 分派
- **`app/services/parser/llm/`**:
  - `role_classifier.py`:LLM 一次调用完成"9 种角色分类 + 投标人身份信息"(US-4.3 任务1+任务2 合并)
  - `price_rule_detector.py`:LLM 识别"sheet 名 / 表头行 / 列映射"
  - `prompts.py`:两个 LLM 调用的 system/user prompt 常量
  - `role_keywords.py`:9 种角色关键词兜底常量(LLM 失败时用)
- **`app/services/parser/pipeline/`**:
  - `run_pipeline.py`:per-bidder 编排协程(extract_content → classify → wait project rule → fill_price)
  - `rule_coordinator.py`:E3 实现(DB 原子 INSERT + asyncio.Event 快路径 + 3s DB poll 慢路径)
  - `progress_broker.py`:project 级 SSE 事件 broker(内存单进程版,含 per-project asyncio.Queue + 订阅者管理)

### 前端

- `pages/projects/ProjectDetailPage.tsx`:接入 SSE,实时更新 bidder 卡片徽章/文件角色徽章/报价规则面板
- `hooks/useParseProgress.ts`:`EventSource` 订阅 + 断线自动降级轮询(3s `GET /api/projects/{pid}`)
- `components/projects/RoleDropdown.tsx`:9 种角色下拉(含"待确认"黄色徽章)+ PATCH 调用
- `components/projects/PriceRulesPanel.tsx`:替换 C4 `PriceRulesPlaceholder`;展示 LLM 识别规则 + 列映射可编辑下拉 + "修正并重新应用"按钮
- `components/projects/ParseProgressIndicator.tsx`:项目顶栏显示整体进度(`N extracted / N identified / N priced / N failed`)
- `services/api.ts`:新增 ~5 方法(patchDocumentRole / subscribeParseProgress / reParseDocument / putPriceRule / listPriceItems)
- `types/index.ts`:新增 `DocumentText / DocumentMetadata / DocumentImage / PriceItem / ParseProgressEvent / ParseStatusExtended`

### 文档联动

- 归档时更新 `docs/handoff.md` §1/§2/§5(C5 决策快照 + 新增 follow-up)
- 不修订 user-stories(实现与描述一致);US-4.3 AC-7 "管理员维护关键词"在 spec 内显式标"本期 Python 常量,C17 升级为 admin UI"

### C4 遗留顺手修

- HTTP 413 / 422 deprecated 常量名 → `HTTP_413_CONTENT_TOO_LARGE` / `HTTP_422_UNPROCESSABLE_CONTENT`(一条 [impl] 任务)

## Capabilities

### New Capabilities

- **`parser-pipeline`**:DOCX/XLSX/图片内容提取 + LLM 角色分类与身份信息提取 + LLM 报价表结构识别(项目级单次)+ 报价数据批量回填 + SSE 完整事件流 + 人工修正角色与列映射

### Modified Capabilities

- **`file-upload`**:`bidders.parse_status` 枚举从 6 态扩到 13 态;`bid_documents.parse_status` 扩 3 态;`price_parsing_rules` 新增 `status` 字段与唯一约束
- **`project-mgmt`**:`ProjectDetailResponse.progress` 从"bidders_total / extracted_count"简单结构扩展为"bidders_total / extracted / identified / priced / failed"分阶段计数

## Impact

- **Affected specs**:新增 `parser-pipeline`;修改 `file-upload`(状态机/约束) + `project-mgmt`(ProjectDetailResponse.progress)
- **Affected code**:backend 新增 ~12 模块 + alembic 0004;frontend 新增 4 组件 + 1 hook + ~5 API 方法
- **Migration**:`alembic upgrade head` 执行 0004;`price_parsing_rules` 新增唯一约束对 C4 已有数据无影响(C4 骨架表为空)
- **Test fixtures**:`clean_users` 扩 4 张新表(document_texts / document_metadata / document_images / price_items)按 FK 顺序清理;`llm_mock.py` 扩展 2 个 programmable fixture(role_classifier_mock / price_rule_detector_mock)用于成功/超时/格式错三分支
- **Follow-up 消化**:C4 "event loop 重启丢任务"由 E3 DB 原子占位消化 50%(报价规则这块);剩余 50%(解压阶段丢任务)仍留 C6 任务表

### 估算规模

~14 Requirement / ~45 Scenario;测试预估 L1 ×60 / L2 ×45 / L3 ×3(主线 / 改角色 / 改列映射)
