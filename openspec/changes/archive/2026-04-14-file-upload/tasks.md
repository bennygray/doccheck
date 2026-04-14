## 1. 后端数据层

- [x] 1.1 [impl] 新增 `backend/app/models/bidder.py`:`Bidder` 模型(字段按 spec "数据模型字段");含 `deleted_at`;内部实现 `get_visible_bidders_stmt(db, user, project_id)` helper 复用 C3 `get_visible_projects_stmt` 模式做项目级权限过滤
- [x] 1.2 [impl] 新增 `backend/app/models/bid_document.py`:`BidDocument` 模型(字段按 spec);无 `deleted_at`(硬删,依附 bidder 生命周期)
- [x] 1.3 [impl] 新增 `backend/app/models/price_config.py`:`ProjectPriceConfig` 1:1 模型(project_id PK+FK)
- [x] 1.4 [impl] 新增 `backend/app/models/price_parsing_rule.py`:`PriceParsingRule` 模型(1 对多)+ JSONB column_mapping
- [x] 1.5 [impl] 更新 `backend/app/models/__init__.py` 注册 4 个新模型
- [x] 1.6 [impl] 新增 `backend/alembic/versions/0003_files.py`:`CREATE TABLE bidders / bid_documents / project_price_configs / price_parsing_rules` + 索引(`(project_id, deleted_at)`)+ 唯一约束(`UNIQUE(project_id, name) WHERE deleted_at IS NULL`)+ FK 定义;含 downgrade 按 FK 顺序 DROP
- [x] 1.7 [impl] 双向迁移验证:`alembic upgrade head` / `alembic downgrade 0002_projects` / `alembic upgrade head`

## 2. 后端服务层 — upload

- [x] 2.1 [impl] 新增 `backend/app/services/upload/validator.py`:
  - `validate_archive_file(file)`:扩展名白名单(zip/7z/rar)+ `python-magic` 魔数校验 + 大小 ≤500MB 校验;违反抛 `UnsupportedMediaType` / `FileTooLarge`
- [x] 2.2 [impl] 新增 `backend/app/services/upload/storage.py`:
  - `save_archive(pid, bid, file) -> (path, md5)`:计算 MD5 + 落盘到 `uploads/{pid}/{bid}/<md5[:16]>_<name>`;返回路径与 MD5
- [x] 2.3 [impl] `backend/pyproject.toml` 新增依赖:`py7zr / rarfile / chardet / python-magic-bin`;`uv sync` 验证

## 3. 后端服务层 — extract(核心安全层)

- [x] 3.1 [impl] 新增 `backend/app/services/extract/safety.py`:
  - `check_safe_entry(entry_path, extract_root)`:normpath + realpath + commonpath 三道校验,返回 bool + 原因
  - `check_size_budget(cumulative_bytes)`:≤2GB 校验
  - `check_count_budget(cumulative_count)`:≤1000 校验
  - `check_nesting_depth(depth)`:≤3 校验
- [x] 3.2 [impl] 新增 `backend/app/services/extract/encoding.py`:
  - `decode_filename(raw_bytes, zip_flag_utf8)`:UTF-8 flag 优先 → chardet 探测 → GBK 默认兜底;探测失败返回原 bytes 的 latin1 解码并标 warning
- [x] 3.3 [impl] 新增 `backend/app/services/extract/engine.py`:
  - `extract_archive(bidder_id, password=None, session_factory=async_session)` 核心函数:
    - 读 bidder → 取压缩包路径 → 按扩展名分派到 zipfile/py7zr/rarfile
    - 循环:每 entry 过 safety 三校验 + 路径 decode;跳过 entry 写 `bid_documents(parse_status=skipped, parse_error=<原因>)`
    - 正常 entry 落盘到 `extracted/{pid}/{bid}/<hash>/<relpath>`;写 `bid_documents(parse_status=extracted)`
    - 嵌套压缩包递归(depth+1);超 3 层标 skipped
    - 加密检测:捕获 `BadZipFile / RuntimeError("Bad password") / py7zr.PasswordRequired` → bidder `parse_status=needs_password`,协程退出
    - 所有异常顶层 catch → bidder `parse_status=failed` + parse_error 前 500 字
- [x] 3.4 [impl] extract 协程入口 helper:`async def trigger_extract(bidder_id, password=None)` 内部 `asyncio.create_task(extract_archive(...))`;模块级变量 `_EXTRACT_DISABLED = os.environ.get("INFRA_DISABLE_EXTRACT") == "1"` 跳过自动起(L2 测试用 fixture 手动调)

## 4. 后端路由 — bidders

- [x] 4.1 [impl] 新增 `backend/app/api/routes/bidders.py`,挂 prefix `/api/projects/{project_id}/bidders`
- [x] 4.2 [impl] `POST /` multipart(name + 可选 file):查 project 可见性 → 查重 name → 创建 bidder → 若有 file:validate → save → write bid_documents 一条 pending + trigger_extract → 返 201
- [x] 4.3 [impl] `GET /`:按 project 可见性返投标人列表,过滤 deleted_at
- [x] 4.4 [impl] `GET /{bid}`:权限过滤 + 返 bidder 详情
- [x] 4.5 [impl] `DELETE /{bid}`:权限过滤 + project.status=analyzing 拒绝(409)+ 软删 bidder + 硬删 bid_documents + shutil.rmtree(extracted)
- [x] 4.6 [impl] `POST /{bid}/upload` 追加上传:validate + save + MD5 去重(同 bidder 内)+ write bid_documents + trigger_extract + 返 201 含 `{new_files, skipped_duplicates}`
- [x] 4.7 [impl] `backend/app/main.py` 注册 bidders router

## 5. 后端路由 — documents + price

- [x] 5.1 [impl] 改造 `backend/app/api/routes/documents.py`(C1 占位):
  - `GET /api/projects/{pid}/bidders/{bid}/documents`:返文件列表(树形由 file_path 前缀组装)
  - `DELETE /api/documents/{id}`:硬删 bid_documents 记录(不删物理压缩包)
  - `GET /api/documents/{id}/download`:返原压缩包文件流;物理文件缺失返 410
  - `POST /api/documents/{id}/decrypt {password}`:状态校验(needs_password 才允许)→ 重新 trigger_extract(password=...)→ 返 202
- [x] 5.2 [impl] 新增 `backend/app/api/routes/price.py`:
  - `GET / PUT /api/projects/{pid}/price-config`(1:1,首次 GET 返 null)
  - `GET / PUT /api/projects/{pid}/price-rules`(列映射骨架,默认 []/允许 PUT 写)
- [x] 5.3 [impl] `backend/app/main.py` 注册 price router
- [x] 5.4 [impl] 改造 `backend/app/api/routes/projects.py` 的 `GET /{id}`:把 `ProjectDetailResponse` 的 `bidders / files / progress` 从固定占位改为真实查询聚合(JOIN bidders + bid_documents 做计数)

## 6. 后端 schema

- [x] 6.1 [impl] 新增 `backend/app/schemas/bidder.py`:`BidderCreate / BidderResponse / BidderSummary / BidderListResponse`
- [x] 6.2 [impl] 新增 `backend/app/schemas/bid_document.py`:`BidDocumentResponse / BidDocumentSummary / UploadResult`(含 new_files / skipped_duplicates)
- [x] 6.3 [impl] 新增 `backend/app/schemas/price.py`:`ProjectPriceConfigRead / ProjectPriceConfigWrite`(含 enum 校验)+ `PriceParsingRuleRead / PriceParsingRuleWrite`(含 column_mapping JSONB schema 校验)
- [x] 6.4 [impl] 改造 `backend/app/schemas/project.py` 的 `ProjectDetailResponse`:把 `bidders / files / progress` 从 `list[Any] / list[Any] / Any | None` 替换为强类型(BidderSummary / BidDocumentSummary / ProjectProgress)

## 7. 前端 — API 与类型

- [x] 7.1 [impl] 扩展 `frontend/src/types/index.ts`:`Bidder / BidderSummary / BidDocument / BidDocumentSummary / ProjectProgress / PriceConfig / PriceParsingRule / UploadResult` 类型
- [x] 7.2 [impl] 扩展 `frontend/src/services/api.ts`:`listBidders / createBidder(multipart) / getBidder / deleteBidder / uploadToBidder(multipart) / listDocuments / deleteDocument / downloadDocument / decryptDocument / getPriceConfig / putPriceConfig / listPriceRules / putPriceRule`(~13 方法);multipart 请求单独封装

## 8. 前端 — 组件

- [x] 8.1 [impl] 新增 `frontend/src/components/projects/AddBidderDialog.tsx`:弹窗(name 输入 + 文件拖拽/选择双入口)+ 原生 file input + drag-drop handler + 前端校验(类型/大小)+ 提交后调 createBidder
- [x] 8.2 [impl] 新增 `frontend/src/components/projects/UploadButton.tsx`:已有投标人的追加上传按钮;重用同文件选择逻辑
- [x] 8.3 [impl] 新增 `frontend/src/components/projects/FileTree.tsx`:按 `file_path` 前缀递归组装树;每节点显示 file_name / 状态徽章(pending/extracting/extracted/skipped/failed/needs_password) / 错误原因展开
- [x] 8.4 [impl] 新增 `frontend/src/components/projects/DecryptDialog.tsx`:密码输入框 → 调 decryptDocument(202 后转轮询)
- [x] 8.5 [impl] 新增 `frontend/src/components/projects/PriceConfigForm.tsx`:币种/含税/单位 3 字段 + PUT 回显
- [x] 8.6 [impl] 新增 `frontend/src/components/projects/PriceRulesPlaceholder.tsx`:空态显示"等待 LLM 识别后展示(C5 上线后可用)";若 listPriceRules 有数据则渲染表格

## 9. 前端 — 页面改造

- [x] 9.1 [impl] 改造 `frontend/src/pages/projects/ProjectDetailPage.tsx`:
  - 替换 `bidders-placeholder`:渲染 Bidder 卡片列表 + "添加投标人"按钮触发 AddBidderDialog + 每卡片含 UploadButton + FileTree + 删除按钮
  - 替换 `files-placeholder`:文件树嵌入 bidder 卡片内
  - 替换 `progress-placeholder`:显示 progress 聚合统计
  - 新增"报价规则"section:展示 PriceConfigForm + PriceRulesPlaceholder
  - 解析中状态自动轮询(`setInterval` 2s,仅在有 bidder 处于 extracting 时启动)

## 10. L1 单元测试

- [x] 10.1 [L1] 新增 `backend/tests/unit/test_extract_safety.py`:zip-slip 三路径校验(`../../../etc/passwd` / 绝对路径 / 符号链接 entry)+ size budget / count budget / nesting depth
- [x] 10.2 [L1] 新增 `backend/tests/unit/test_extract_encoding.py`:UTF-8 flag / GBK / chardet fallback / 乱码兜底
- [x] 10.3 [L1] 新增 `backend/tests/unit/test_upload_validator.py`:魔数 vs 扩展名匹配;大小越界
- [x] 10.4 [L1] 新增 `backend/tests/unit/test_bidder_schema.py`:BidderCreate 校验(name 空/超长/合法)
- [x] 10.5 [L1] 新增 `backend/tests/unit/test_price_schemas.py`:price config 枚举拒非法;column_mapping JSONB 结构校验
- [x] 10.6 [L1] 新增 `frontend/src/components/projects/AddBidderDialog.test.tsx`:name 空拒提交;大文件拒收;类型不匹配提示
- [x] 10.7 [L1] 新增 `frontend/src/components/projects/FileTree.test.tsx`:空/扁平/嵌套三种数据渲染
- [x] 10.8 [L1] 新增 `frontend/src/components/projects/PriceConfigForm.test.tsx`:空初始 → 填表 → 回显
- [x] 10.9 [L1] 命令验证:`pytest backend/tests/unit/` 全绿(98 pass) + `cd frontend && npm test` 全绿(32 pass)

## 11. L2 后端 API E2E

- [x] 11.1 [L2] 新增 `backend/tests/fixtures/archive_fixtures.py`:生成测试用压缩包 factory(正常 ZIP / zip-bomb mock / zip-slip / 嵌套 / GBK 编码 / 损坏 / 空 / 加密)+ MD5 预知
- [x] 11.2 [L2] 扩展 `backend/tests/fixtures/auth_fixtures.py` 的 `clean_users`:按 FK 顺序加 `delete bid_documents → delete bidders → delete price_parsing_rules → delete project_price_configs`(再走原有 delete projects / delete users)
- [x] 11.3 [L2] 新增 `backend/tests/e2e/test_bidders_api.py`:覆盖 spec "投标人 CRUD" 9 个 Scenario
- [x] 11.4 [L2] 新增 `backend/tests/e2e/test_upload_api.py`:覆盖 spec "文件上传(创建+追加)" 8 个 Scenario;`INFRA_DISABLE_EXTRACT=1` 跳过自动解压,测试手动调验证
- [x] 11.5 [L2] 新增 `backend/tests/e2e/test_extract_api.py`:覆盖 spec "压缩包安全解压" 9 个 Scenario;手动 await `extract_archive` 后断言 DB 状态
- [x] 11.6 [L2] 新增 `backend/tests/e2e/test_decrypt_api.py`:覆盖 spec "加密压缩包密码重试" 4 个 Scenario
- [x] 11.7 [L2] 新增 `backend/tests/e2e/test_documents_api.py`:覆盖 spec "文件列表与解析状态" 3 个 + "文件下载与删除" 4 个 = 7 个 Scenario
- [x] 11.8 [L2] 新增 `backend/tests/e2e/test_price_api.py`:覆盖 spec "项目报价元配置" 5 个 + "报价列映射规则骨架" 5 个 = 10 个 Scenario
- [x] 11.9 [L2] 新增 `backend/tests/e2e/test_project_detail_with_files.py`:覆盖 project-mgmt MODIFIED 的 3 个 Scenario(真实 bidders 摘要 / 空项目零进度 / 列表 risk_level 仍 null)
- [x] 11.10 [L2] 命令验证:`pytest backend/tests/e2e/` 全绿(所有 C2/C3/C4 不回归)

## 12. L3 UI E2E

- [x] 12.1 [L3] 新增 `e2e/fixtures/archive-fixtures.ts`:写一个真实小 ZIP 到 tmp(~2 个 docx + 1 个 jpg)供 setInputFiles 使用
- [x] 12.2 [L3] 新增 `e2e/tests/c4-upload-main.spec.ts`:登录 → 建项目 → 添加投标人(名称 + ZIP)→ 轮询等 parse_status=extracted → 展开文件树看到文件 → 删除投标人 → 列表更新
- [x] 12.3 [L3] 新增 `e2e/tests/c4-encrypted-archive.spec.ts`:加密 ZIP 上传 → 轮询到 needs_password → 打开 DecryptDialog → 输错密码看错误 → 输对密码 → 等 extracted → 断言文件树
- [x] 12.4 [L3] 命令验证:`npx playwright test` 全绿(12/12 pass);若 flaky(大文件上传时序)→ 按 CLAUDE.md 约定降级手工+截图,截图写 `e2e/artifacts/c4-<日期>/` 并在任务条目贴路径

## 13. 文档联动

- [x] 13.1 [manual] 更新 `backend/README.md`(或项目 README):新增"C4 依赖准备"段落:Windows/Linux libmagic 装法;unrar 可选装法;`uploads/` `extracted/` 目录自动创建;部署需配 `client_max_body_size=500M`(nginx)或 uvicorn 等价限制
- [x] 13.2 [manual] 更新 `.gitignore`:新增 `backend/uploads/` `backend/extracted/`
- [x] 13.3 [manual] 更新 `docs/handoff.md`:§1 状态 / §2 本次 session 决策(A2/B1/C2/D2 理由 + D1~D10 实施内选)/ §3 follow-up 加"event loop 重启丢任务"与"密码 3 次冻结 → C17"两条 / §5 最近变更历史追加 C4 归档条目

## 14. 总汇

- [x] 14.1 跑 [L1][L2][L3] 全部测试,全绿(L1 backend 98 + L1 frontend 32 + L2 101 + L3 12 = 243 pass)
