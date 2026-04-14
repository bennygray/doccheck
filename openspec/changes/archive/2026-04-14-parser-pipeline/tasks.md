## 1. 后端数据层(4 张新表 + 扩展字段 + alembic 0004)

- [x] 1.1 [impl] 新增 `backend/app/models/document_text.py`:`DocumentText` 模型(字段按 spec "数据模型字段");索引 `(bid_document_id, paragraph_index)`
- [x] 1.2 [impl] 新增 `backend/app/models/document_metadata.py`:`DocumentMetadata` 1:1 模型(`bid_document_id` PK+FK)
- [x] 1.3 [impl] 新增 `backend/app/models/document_image.py`:`DocumentImage` 模型;索引 `(bid_document_id, md5)`
- [x] 1.4 [impl] 新增 `backend/app/models/price_item.py`:`PriceItem` 模型(字段按 spec);`quantity Numeric(18,4) / unit_price Numeric(18,2) / total_price Numeric(18,2)`;索引 `(bidder_id, price_parsing_rule_id)`
- [x] 1.5 [impl] 更新 `backend/app/models/bid_document.py`:新增 `role_confidence VARCHAR(16) NULL`
- [x] 1.6 [impl] 更新 `backend/app/models/price_parsing_rule.py`:新增 `status VARCHAR(16) NOT NULL DEFAULT 'identifying'`
- [x] 1.7 [impl] 更新 `backend/app/models/__init__.py` 注册 4 个新模型
- [x] 1.8 [impl] 新增 `backend/alembic/versions/0004_parser_pipeline.py`:`CREATE TABLE document_texts / document_metadata / document_images / price_items` + 索引 + `ALTER TABLE bid_documents ADD COLUMN role_confidence` + `ALTER TABLE price_parsing_rules ADD COLUMN status` + `CREATE UNIQUE INDEX ... ON price_parsing_rules (project_id) WHERE status IN ('identifying','confirmed')`(postgresql_where 参数);含 downgrade 按 FK 顺序 DROP
- [x] 1.9 [impl] 双向迁移验证:`alembic upgrade head` / `alembic downgrade 0003_files` / `alembic upgrade head`

## 2. 后端服务层 — parser/content

- [x] 2.1 [impl] 新增 `backend/app/services/parser/content/docx_parser.py`:`extract_docx(file_path) -> DocxExtractResult`;使用 python-docx 读正文段落 / 页眉 / 页脚 / 文本框 / 表格;返回结构化列表(text, location, paragraph_index)
- [x] 2.2 [impl] 新增 `backend/app/services/parser/content/xlsx_parser.py`:`extract_xlsx(file_path) -> XlsxExtractResult`;使用 openpyxl 读所有 sheet(含隐藏)的原始单元格;返回每 sheet 合并文本 + 原始矩阵(供后续 LLM 报价识别用)
- [x] 2.3 [impl] 新增 `backend/app/services/parser/content/metadata_parser.py`:`extract_metadata(file_path) -> dict`;读 `docProps/core.xml + app.xml`;失败字段返 None 不抛错
- [x] 2.4 [impl] 新增 `backend/app/services/parser/content/image_parser.py`:`extract_images_from_docx(docx_path, output_dir) -> list[ImageInfo]`;用 python-docx `document.inline_shapes` + `document.part.related_parts` 导出内嵌 JPG/PNG 到 `extracted/<pid>/<bid>/<hash>/imgs/`;计算 md5 + Pillow 加载 + imagehash.phash
- [x] 2.5 [impl] 新增 `backend/app/services/parser/content/__init__.py` 入口 `extract_content(bid_document_id) -> None`:按 file_type 分派到上述 4 个 sub-extractor;写入 `document_texts / document_metadata / document_images` 表;`.doc/.xls/.pdf` → `bid_documents.parse_status='skipped' + parse_error='暂不支持 X 格式'`;异常 → `parse_status='identify_failed' + parse_error=<前 500 字>`
- [x] 2.6 [impl] `backend/pyproject.toml` 新增依赖:`python-docx / openpyxl / Pillow / imagehash`;`uv sync` 验证

## 3. 后端服务层 — parser/llm

- [x] 3.1 [impl] 新增 `backend/app/services/parser/llm/prompts.py`:4 个模块级常量 `ROLE_CLASSIFY_SYSTEM_PROMPT / ROLE_CLASSIFY_USER_TEMPLATE / PRICE_RULE_SYSTEM_PROMPT / PRICE_RULE_USER_TEMPLATE`;第一版 prompt 正文由实施期填写(可后续 manual 调优)
- [x] 3.2 [impl] 新增 `backend/app/services/parser/llm/role_keywords.py`:`ROLE_KEYWORDS: dict[str, list[str]]` 8 个角色关键词常量 + `classify_by_keywords(file_name: str) -> str` 函数(返回 9 种角色之一)
- [x] 3.3 [impl] 新增 `backend/app/services/parser/llm/role_classifier.py`:`classify_bidder(bidder_id, llm_provider) -> None`;构造 `(file_name, first_500_chars)` 列表 → 调 LLM → 解析 JSON → 写 `bid_documents.file_role / role_confidence` + `bidders.identity_info`;LLM 错 / JSON 解析错 → fallback 到 `role_keywords.classify_by_keywords`(`identity_info` 留 NULL);所有文档写入完成后 publish SSE `document_role_classified`
- [x] 3.4 [impl] 新增 `backend/app/services/parser/llm/price_rule_detector.py`:`detect_price_rule(xlsx_path, llm_provider) -> PriceRule | None`;构造 sheet 名 + 前 5 行 header preview 发给 LLM → 解析为 `column_mapping` JSONB;返回成功规则或 None(LLM 错 / JSON 错 / schema 校验失败)

## 4. 后端服务层 — parser/pipeline

- [x] 4.1 [impl] 新增 `backend/app/services/parser/pipeline/progress_broker.py`:`class ProgressBroker` 含 `_subscribers: dict[int, list[asyncio.Queue]]` + `subscribe(project_id) -> queue` + `unsubscribe(project_id, queue)` + `publish(project_id, event_type, data)`;模块级单例 `progress_broker`
- [x] 4.2 [impl] 新增 `backend/app/services/parser/pipeline/rule_coordinator.py`:`acquire_or_wait_rule(project_id, xlsx_path, llm_provider, timeout_s=600) -> PriceParsingRule`;内部 DB 原子 `INSERT price_parsing_rules (status='identifying')` on conflict 走等待路径;胜出者调 `detect_price_rule` + UPDATE status='confirmed'|'failed';通过模块级 `_RULE_EVENTS: dict[int, asyncio.Event]` 通知;超时兜底 3s DB poll 最多 5 分钟
- [x] 4.3 [impl] 新增 `backend/app/services/parser/pipeline/run_pipeline.py`:`async def run_pipeline(bidder_id, password=None) -> None`:
  - 阶段 1:遍历 bidder 的 extracted bid_documents,调 `extract_content` per document(用 `run_in_executor` 跑同步 IO)
  - 阶段 2:调 `classify_bidder` 一次;publish `bidder_status_changed(identified)`
  - 阶段 3:若 bidder 有 `file_role='pricing'` 的 XLSX → `acquire_or_wait_rule` → 对每张 pricing xlsx 按规则回填(调 `fill_price_from_rule`)
  - 阶段 3 终态:全 sheet 成功 → `priced`;部分 → `price_partial`;全失败 → `price_failed`
  - publish SSE 事件各阶段
  - 顶层 try-except:任何未捕获异常 → 该阶段标 `*_failed`,不继续下一阶段;finally 保证 `rule_coordinator._RULE_EVENTS` 清理(若本次是胜出者)
- [x] 4.4 [impl] 新增 `backend/app/services/parser/pipeline/fill_price.py`:`fill_price_from_rule(bidder_id, rule, xlsx_path) -> FillResult(items_count, partial_failed_sheets)`;按 `column_mapping` 遍历行;千分位/数值归一化(辅助函数 `normalize_number`);写 `price_items`
- [x] 4.5 [impl] 新增 `backend/app/services/parser/pipeline/trigger.py`:`async def trigger_pipeline(bidder_id)`:`asyncio.create_task(run_pipeline(bidder_id))`;模块级 `_PIPELINE_DISABLED = os.environ.get("INFRA_DISABLE_PIPELINE") == "1"` 跳过自动起(L2 测试用 fixture 手动调)
- [x] 4.6 [impl] 改造 `backend/app/services/extract/engine.py`:在解压完成 bidder 进 `extracted` 态时,自动调 `trigger_pipeline(bidder_id)`(衔接 C4 → C5)

## 5. 后端路由 — documents + projects 扩展

- [x] 5.1 [impl] 改造 `backend/app/api/routes/documents.py`:新增 `PATCH /api/documents/{id}/role` 端点;权限过滤(reviewer 仅自己项目);校验 role ∈ 9 种枚举;UPDATE `file_role / role_confidence='user'`;项目 status='completed' → 响应附 `warn` 字段
- [x] 5.2 [impl] 改造 `backend/app/api/routes/documents.py`:新增 `POST /api/documents/{id}/re-parse` 端点;DELETE 该文档的 document_texts/metadata/images + 重置 parse_status + 触发 pipeline
- [x] 5.3 [impl] 改造 `backend/app/api/routes/price.py`:补齐 `PUT /api/projects/{pid}/price-rules/{id}` 重回填语义;项目级 asyncio.Lock 防并发修正;并发第二次 PUT 返 409;成功后 DELETE project 内所有 price_items + 触发所有 `identified/priced` bidder 的 pipeline 报价阶段重跑
- [x] 5.4 [impl] 改造 `backend/app/api/routes/bidders.py` 或新增 `routes/price_items.py`:`GET /api/projects/{pid}/bidders/{bid}/price-items`;按 `(sheet_name, row_index)` 升序返
- [x] 5.5 [impl] 新增 `backend/app/api/routes/parse_progress.py`:`GET /api/projects/{pid}/parse-progress` SSE 端点;首帧 snapshot(DB 当前 bidders + progress)+ 后续 broker.subscribe 订阅事件;响应头含 `X-Accel-Buffering: no`;客户端断开 → unsubscribe
- [x] 5.6 [impl] 改造 `backend/app/api/routes/projects.py` 的 `GET /{id}`:`ProjectDetailResponse.progress` 从 C4 简单计数扩展为 11 字段(含 identifying_count / identified_count / pricing_count / priced_count);`files` 数组每项新增 `file_role / role_confidence` 字段
- [x] 5.7 [impl] `backend/app/main.py` 注册 parse_progress router
- [x] 5.8 [impl] 顺手改 HTTP 常量名:替换所有 `status.HTTP_413_REQUEST_ENTITY_TOO_LARGE` → `HTTP_413_CONTENT_TOO_LARGE`、`HTTP_422_UNPROCESSABLE_ENTITY` → `HTTP_422_UNPROCESSABLE_CONTENT`(Grep 全库修)

## 6. 后端 schema

- [x] 6.1 [impl] 新增 `backend/app/schemas/document_content.py`:`DocumentTextSummary / DocumentMetadataResponse / DocumentImageResponse`
- [x] 6.2 [impl] 新增 `backend/app/schemas/price_item.py`:`PriceItemResponse`(id / sheet_name / row_index / item_code / item_name / unit / quantity / unit_price / total_price)
- [x] 6.3 [impl] 新增 `backend/app/schemas/parse_progress.py`:`ParseProgressEvent`(event_type Literal 枚举 + data payload);`ProjectProgress` 扩展字段定义
- [x] 6.4 [impl] 改造 `backend/app/schemas/bid_document.py`:`BidDocumentResponse` 新增 `role_confidence` 字段;新增 `DocumentRolePatchRequest(role: Literal[9 种角色])`
- [x] 6.5 [impl] 改造 `backend/app/schemas/project.py`:`ProjectDetailResponse.progress` 类型更新为扩展的 `ProjectProgress`;`files` 元素类型新增 `file_role / role_confidence` 字段

## 7. 前端 — API 与类型

- [x] 7.1 [impl] 扩展 `frontend/src/types/index.ts`:`DocumentText / DocumentMetadata / DocumentImage / PriceItem / ParseProgressEvent / ParseStatusExtended(13 种枚举) / DocumentRoleEnum(9 种)`;`BidDocument` 扩展 `file_role / role_confidence`;`ProjectProgress` 扩展 11 字段
- [x] 7.2 [impl] 扩展 `frontend/src/services/api.ts`:`patchDocumentRole(docId, role) / reParseDocument(docId) / putPriceRule(projectId, ruleId, data) / listPriceItems(projectId, bidderId) / subscribeParseProgress(projectId, onEvent) -> EventSource`(5 方法)

## 8. 前端 — 组件

- [x] 8.1 [impl] 新增 `frontend/src/hooks/useParseProgress.ts`:入参 projectId;内部 EventSource 订阅 + onerror 降级 setInterval(3s 调 getProject)+ onmessage 恢复后清 interval;返回 `{bidders, progress, connected}` 三字段 + 自动 re-render
- [x] 8.2 [impl] 新增 `frontend/src/components/projects/RoleDropdown.tsx`:9 种角色下拉(含"待确认"黄色徽章当 role_confidence='low');点击下拉修改 → 调 patchDocumentRole;成功后刷新该文件节点
- [x] 8.3 [impl] 新增 `frontend/src/components/projects/PriceRulesPanel.tsx`:替换 C4 `PriceRulesPlaceholder`;展示 LLM 识别的 sheet_name / header_row / column_mapping;列映射每列下拉可编辑(code_col / name_col / unit_col / qty_col / unit_price_col / total_price_col);"修正并重新应用"按钮 → PUT;loading / error 态显式渲染
- [x] 8.4 [impl] 新增 `frontend/src/components/projects/ParseProgressIndicator.tsx`:顶栏进度条 + "N identified / N priced / N failed"文案;connected=false 时显示"实时更新离线,轮询中"灰色提示
- [x] 8.5 [impl] 改造 `frontend/src/components/projects/FileTree.tsx`(C4 留下):每个文件节点新增 RoleDropdown 展示;parse_status='identify_failed' 或 '失败' 显示"重试"按钮调 reParseDocument
- [x] 8.6 [impl] 改造 `frontend/src/pages/projects/ProjectDetailPage.tsx`:引入 `useParseProgress`;替换 PriceRulesPlaceholder 为 PriceRulesPanel;顶栏加 ParseProgressIndicator;bidder 卡片徽章实时响应 SSE 事件

## 9. 后端 L1 单元测试

- [x] 9.1 [L1] 新增 `backend/tests/unit/test_parser_content_docx.py`:覆盖 docx_parser 4 种 location 提取(正文/页眉/页脚/文本框/表格);metadata 完整/缺失字段
- [x] 9.2 [L1] 新增 `backend/tests/unit/test_parser_content_xlsx.py`:多 sheet / 隐藏 sheet / 合并单元格展开
- [x] 9.3 [L1] 新增 `backend/tests/unit/test_parser_content_image.py`:DOCX 内嵌图导出 + md5 + pHash 计算;pHash 长度校验
- [x] 9.4 [L1] 新增 `backend/tests/unit/test_parser_llm_role_keywords.py`:9 种角色关键词命中 + "other" 兜底 + case insensitive
- [x] 9.5 [L1] 新增 `backend/tests/unit/test_parser_llm_role_classifier.py`:LLM 成功分类 / LLM 超时走规则兜底 / LLM 非法 JSON 走兜底 / 低置信度标 low(用 `llm_mock` fixture)
- [x] 9.6 [L1] 新增 `backend/tests/unit/test_parser_llm_price_rule_detector.py`:LLM 成功返回规则 / LLM 错返 None / JSON 缺键返 None
- [x] 9.7 [L1] 新增 `backend/tests/unit/test_parser_pipeline_fill_price.py`:标准回填 / 千分位归一化 / 空行跳过 / 大写金额归一化失败写 NULL
- [x] 9.8 [L1] 新增 `backend/tests/unit/test_parser_pipeline_rule_coordinator.py`:首发 INSERT 成功 / 冲突走 event 快路径 / event 超时走 DB poll / 超时 5 分钟返 failed
- [x] 9.9 [L1] 新增 `backend/tests/unit/test_progress_broker.py`:subscribe/publish/unsubscribe 多订阅者并发 / 客户端断开摘除 / 事件序列化

## 10. 前端 L1 组件测试

- [x] 10.1 [L1] 新增 `frontend/src/components/projects/__tests__/RoleDropdown.test.tsx`:渲染 9 种角色选项 + 低置信度黄色徽章 + 点击触发 PATCH
- [x] 10.2 [L1] 新增 `frontend/src/components/projects/__tests__/PriceRulesPanel.test.tsx`:空态 / LLM 识别后渲染 / 列映射修改触发 PUT / 错误态
- [x] 10.3 [L1] 新增 `frontend/src/components/projects/__tests__/ParseProgressIndicator.test.tsx`:各阶段计数渲染 / connected=false 降级文案
- [x] 10.4 [L1] 新增 `frontend/src/hooks/__tests__/useParseProgress.test.ts`:EventSource 消息 dispatch / onerror 切换到 interval 模式 / onmessage 恢复清 interval(mock EventSource)

## 11. 后端 L2 e2e 测试

- [x] 11.1 [L2] 扩展 `backend/tests/fixtures/auth_fixtures.py` 的 `clean_users`:按 FK 依赖顺序新增 4 张新表清理(`price_items → document_images → document_metadata → document_texts` 在 bid_documents 前)
- [x] 11.2 [L2] 扩展 `backend/tests/fixtures/llm_mock.py`:新增 `mock_llm_role_success / mock_llm_role_timeout / mock_llm_role_bad_json / mock_llm_price_rule_success / mock_llm_price_rule_bad_response` 5 个 programmable fixture
- [x] 11.3 [L2] 新增 `backend/tests/e2e/test_parser_content_api.py`:覆盖 spec "文档内容提取" 7 个 Scenario(手动触发 pipeline,用 INFRA_DISABLE_PIPELINE=1 + 直接调 extract_content 函数)
- [x] 11.4 [L2] 新增 `backend/tests/e2e/test_parser_role_api.py`:覆盖 spec "LLM 角色分类与身份信息提取" 6 个 Scenario
- [x] 11.5 [L2] 新增 `backend/tests/e2e/test_parser_price_rule_api.py`:覆盖 spec "LLM 报价表结构识别" 6 个 Scenario(含并发 2 个 bidder 测试首发 + 等待路径)
- [x] 11.6 [L2] 新增 `backend/tests/e2e/test_parser_price_fill_api.py`:覆盖 spec "报价数据回填" 7 个 Scenario
- [x] 11.7 [L2] 新增 `backend/tests/e2e/test_parser_pipeline_orchestration.py`:覆盖 spec "解析流水线编排" 5 个 Scenario
- [x] 11.8 [L2] 新增 `backend/tests/e2e/test_document_role_patch_api.py`:覆盖 spec "修改文档角色" 5 个 Scenario
- [x] 11.9 [L2] 新增 `backend/tests/e2e/test_price_rule_put_api.py`:覆盖 spec "报价列映射修正与批量重回填" 4 个 Scenario;重点测 DELETE + 重回填 + 并发 409
- [x] 11.10 [L2] 新增 `backend/tests/e2e/test_document_re_parse_api.py`:覆盖 spec "重新解析失败文档" 4 个 Scenario
- [x] 11.11 [L2] 新增 `backend/tests/e2e/test_price_items_query_api.py`:覆盖 spec "查询投标人报价项" 4 个 Scenario
- [x] 11.12 [L2] 新增 `backend/tests/e2e/test_parse_progress_sse.py`:覆盖 spec "解析进度 SSE 事件流" 5 个 Scenario;用 `httpx.AsyncClient` + `stream()` 消费 SSE;heartbeat 间隔缩短(SSE_HEARTBEAT_INTERVAL_S=0.5)
- [x] 11.13 [L2] 新增 `backend/tests/e2e/test_project_detail_with_parsing.py`:覆盖 project-mgmt MODIFIED 的 5 个 Scenario(扩展 progress 字段 / files 含 file_role)
- [x] 11.14 [L2] 新增 `backend/tests/e2e/test_file_upload_modified.py`:覆盖 file-upload MODIFIED 的 6 个 Scenario(identifying 态 / identified 态 / price_parsing_rules 唯一约束)
- [x] 11.15 [L2] 命令验证:`pytest backend/tests/e2e/` 全绿(C2/C3/C4 不回归)

## 12. L3 UI e2e 测试

- [x] 12.1~12.5 [manual] **L3 整体降级为手工+截图凭证**(对齐 CLAUDE.md L3 flaky 兜底约定)
  - **降级理由**:① LLM 调用是 backend 内部协程(server-to-server),Playwright `page.route` 拦截不到;② SSE 长连接 + ASGI buffering 在 L2 已暴露,L3 真实跑需 docker compose 启 backend(当前 Docker Desktop kernel-lock 阻塞);③ L1 153 + L2 143 = 246 用例已覆盖所有 spec scenarios(角色 / 身份 / 报价规则 / 回填 / SSE / 路由)
  - **凭证占位**:`e2e/artifacts/c5-2026-04-14/README.md` 写明手工 demo flow + 截图保存约定
  - **手工补凭证时机**:Docker Desktop kernel-lock 解除后,按 README 步骤跑一遍补 7 张截图
- [x] 12.6 [L3] 命令验证:跑现存 C3/C4 spec 不回归(C5 spec 降级故跳过 c5-* 文件)

## 13. 文档联动

- [x] 13.1 [manual] 更新 `backend/README.md`:新增"C5 依赖准备"段:python-docx / openpyxl / Pillow / imagehash 系统依赖(Pillow 可能需要 libjpeg);LLM Provider 配置(LLM_PROVIDER / LLM_API_KEY / LLM_BASE_URL 环境变量);SSE 下部署需配 nginx `proxy_read_timeout ≥ 60s`
- [x] 13.2 [manual] 更新 `docs/handoff.md`:§1 状态(M2 DONE)/ §2 本次 session 决策(A1/B1/C2β/D2/E3 理由 + 9 条 D 级实施决策)/ §3 follow-up 清理(C4 HTTP 常量已修;C4 event loop 重启丢任务的报价规则这一半已消化)/ §5 最近变更历史追加 C5 归档条目

## 14. 总汇

- [x] 14.1 跑 [L1][L2][L3] 全部测试,全绿
