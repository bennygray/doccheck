# 项目 Handoff

> **跨会话/跨人接手的现场视角快照。** 计划视角见 `docs/execution-plan.md` §5。
>
> 本文档职责:记录"现在人在哪、下一步干什么、有什么没说清"。
> 最近变更历史只保留 5 条,更早历史去 `git log` 查。

---

## 1. 当前状态快照

| 项 | 值 |
|---|---|
| 当前里程碑 | M2 进行中(C3+C4 已实施完,2/3) |
| 当前 change | C4 `file-upload` apply 完成,待归档 |
| 当前任务行 | N/A |
| 最新 commit | 待本次 archive commit(`归档 change: file-upload(M2)`) |
| 工作区 | C4 全量改动:backend 4 模型 + 0003 迁移 + upload/extract 服务 + 3 路由(bidders / documents / price)+ 3 schemas + auth_fixtures 扩 4 表清理 + L1×45 + L2×50;frontend 6 组件 + ProjectDetailPage 重写 + types/api 扩 ~13 方法 + L1×9;e2e 2 个 c4 spec + 加密包 fixture;`vite.config.ts` 顺手修 ts 错误;`backend/README.md` 新建,`.gitignore` 加 uploads/extracted。**测试合计 243 全绿**(L1 130 / L2 101 / L3 12)|

---

## 2. 本次 session 关键决策(2026-04-14,C4 apply 阶段)

### propose 阶段已敲定(本次未变更)

- **A2 整体做**:不拆 C4a/C4b,接受 ~12 Req / ~38 Scenario(实际落地 9 Req / 50 L2 scenario)
- **B1 minimal asyncio.create_task**:解压走单进程协程;Process Pool 升级留 C6
- **C2 元配置 + 列映射骨架**:报价规则元配置完整做,列映射只建 GET/PUT 端点骨架
- **D2 检测+标记+密码重试无冻结**:加密包检测 + 密码重试,3 次冻结留 C17
- **D1~D10 实施细节**:见 `openspec/changes/file-upload/design.md`

### apply 阶段就地敲定

- **`upload_dir / extracted_dir` 必须 resolve 为绝对路径**:storage 落盘后把绝对路径写进 `bid_documents.file_path`,extract 不做"相对路径再 join 一次 settings.upload_dir"的危险拼接 — L2 全测都跑通后才发现 L3 在不同 cwd 下读不到文件,加 resolve 后修复(commit 内修)
- **GBK 文件名 cp437 视图回路**:zipfile 在 0x800 flag 撒谎(很多 7-Zip Windows 给非 ASCII 中文就置 flag),engine 不能简单按 flag 走 utf-8;落地策略:总是 try cp437 字节回路 → GBK 解,若 GBK 解出落入"中日韩 / 全 ASCII"区间则用,否则信原 unicode info.filename。`decode_filename` 调整为 GBK 优先(覆盖中文场景多数)+ chardet 兜底
- **加密包密码错误识别**:py7zr 对 wrong password 抛各种异常(`TypeError("Unknown field: b'5'")` 等无 "password" 关键字)→ engine 改两阶段:先无密码 probe 探测 `is_encrypted`,再带密码 extract;后阶段任何异常都视为"密码错"而非"压缩包损坏"
- **bid_documents 表既存归档行又存解压条目**:用 `file_type` ∈ {`.zip/.7z/.rar`} + `parse_status` ∈ {pending/extracting/...} 区分顶层归档行 vs 跳过子归档行 vs 普通解压文件;UNIQUE(bidder_id, md5) 约束同时承担"同 bidder 同 archive 去重"与"同 bidder 同文件去重"
- **decrypt 端点恒返 202 而非 400 区分对错**:design 的"async 即触即返"决定了密码对错由后续轮询观察 `parse_status` 得知,与 spec scenario "响应 400" 字面冲突 → 落地以 design 为准(L2 已覆盖"输错后状态回到 needs_password")
- **L2 fixture clean_users 按 FK 顺序新增 4 行 delete**:bid_documents → bidders → price_parsing_rules → project_price_configs(在原 projects/users 之前)
- **小坑**:`bidders.parse_status` 聚合规则 = 任一 needs_password → 整体 needs_password;extracting → 整体 extracting;否则按 extracted/partial/failed 多数态。aggregate 函数固定在 engine `_aggregate_bidder_status`
- **顺手修了 vite.config.ts 的 test 字段类型错**(改 import 自 `vitest/config`),C3 follow-up 清掉

### 文档联动

- **`backend/README.md` 新建**:列 C4 系统依赖(libmagic / unrar)+ 运行时目录 + nginx client_max_body_size 提示
- **`.gitignore` 加 uploads/extracted**:含 `backend/uploads/` `backend/extracted/`
- **execution-plan.md** 暂未追加 §6 计划变更行(本次未调整粒度/顺序,仅落地 C4 既定计划)

---

## 2.bak 上一 session 决策(2026-04-14,C3 propose + apply 阶段)

### 设计层面(propose 敲定)

- **删除语义 = 软删除** `deleted_at TIMESTAMP NULL`(选项 A);与 `docs/execution-plan.md` §C3 验证场景 4 一致;同步**修订** `docs/user-stories.md` US-2.4(原"硬删")
- **权限过滤下沉到查询层**(`get_visible_projects_stmt` helper),所有读取路径必经此函数,杜绝"忘加过滤"
- **reviewer 访问他人项目 = 404 而非 403**(防项目存在性泄露)
- **status 字段 = VARCHAR + 应用层枚举**(不引状态机库;C6 推进状态时只改 helper 不改字段类型)
- **金额精度 = `Numeric(18, 2)`**(精度需求到元/2 位小数,与 C11/C12 报价分析未来对比对齐)
- **分页 = page+size**(默认 size=12,上限 100;不上游标)
- **不引 form 库**(列表/创建/详情全部原生 useState,与 C2 LoginPage/ChangePasswordPage 风格一致)
- **L3 主线 = 单 spec 串联**(`c3-project-crud.spec.ts` 单文件 8 步;不拆 4 个 spec 避免状态恢复成本)
- **同名项目 = 直接允许**(US-2.1 AC-5 明确;execution-plan "幂等"以 US 为准)

### apply 阶段就地敲定

- **size 上限策略锁死 = 422**(spec.md 留二选一,L2 选拒绝;FastAPI Query `le=100` 自动返 422)
- **`clean_users` fixture 扩展清 projects**(放在 yield 前后,FK 依赖顺序 `delete projects → delete users`):C2 fixture 文件加 4 行,使所有 C2/C3/未来新表共享同一清理入口
- **C4+ 占位字段 = ProjectDetailResponse 默认值**(`bidders=[] / files=[] / progress=null`),不在路由层手填,避免 C4 上线时遗漏更新
- **smoke-home.spec.ts 适配新 ProjectListPage**(删 `health-status` 测点;h1 由"围标检测系统"改"项目列表"):随 C3 一起进 commit,不留出回归
- **detail/list 共享 `_fetch_visible_project` helper**(取行后统一 404),避免 reviewer-vs-others 的判断重复实现

### 实施阶段关键技术坑

- **L2 第一次跑全红 = FK 违反**:`clean_users` 在 yield 后跑 `DELETE FROM users` 时,projects 表持有 FK,asyncpg 报 `ForeignKeyViolationError`。Fix:`auth_fixtures.py` 的 `clean_users` 在清 users 前先清 projects(C3 是首张子表,后续每张子表加进来都要往这里加一行 delete)
- **删 `ProjectsPlaceholderPage` 触发 L3 smoke 回归**:`smoke-home.spec.ts` 依赖 `data-testid="health-status"` 与 `<h1>围标检测系统</h1>`。修复在同一 PR/commit 里完成:适配新 h1("项目列表")+ 移除 health-status 断言(改为只测 `/api/health` 代理可达性,不再要求前端展示)
- **window.confirm 在 Playwright 下默认 cancel**:c3 spec 里 `beforeEach` 注册 `page.on("dialog", d => d.accept())` 一次性解决所有删除/警告对话框
- **vite.config.ts 预存在 ts 错误**:`{ test: ... }` 不在 UserConfigExport 类型里(vitest 类型未合并);C3 范围内未触碰,留作 follow-up
- **`mapped_column` 写错位的笔误**:第一稿在 Project 模型里把 `from sqlalchemy.orm import Mapped` 放进了类内,然后 `id: Mapped_int = None` 占位 — 立刻发现并整体重写为标准 import 顶部 + 类体只放字段定义。教训:模型类不要嵌套 import

### 文档联动

- **修订 `docs/user-stories.md` US-2.4**:AC-3 由"硬删除并清盘" → "软删除(`deleted_at`)+ 文件清理移交生命周期任务";新增 AC-4 "非 owner 返 404 防存在性泄露";追加 `[Change History]` 行注明 C3 修订
- **execution-plan.md** 暂未追加 §6 计划变更行(本次未调整粒度/顺序,仅落地 C3 既定计划,无需写入)

---

## 3. 待确认 / 阻塞

- 无硬阻塞,M2 进度 2/3。C4 已实施完,待 archive。
- **Follow-up(C4 新增)**:`asyncio.create_task` 协程在 event loop 重启时丢任务,bidder 永久卡 `extracting`。Mitigation 留 C6 任务表上线后扫描"卡住"状态恢复。当前缺 admin 重置端点
- **Follow-up(C4 新增)**:加密包 3 次密码错冻结(原 D2 决策推到 C17)未实现;当前可无限重试
- **Follow-up(C4 新增)**:HTTP 413 / 422 用了 deprecated 常量名(FastAPI 警告),可 C5 顺手改 `HTTP_413_CONTENT_TOO_LARGE` / `HTTP_422_UNPROCESSABLE_CONTENT`
- **Follow-up(C4 新增)**:`e2e/fixtures/encrypted-sample.7z`(250 字节)由 backend fixture 生成,**未入库**(在 .gitignore 兜底之外不在);CI 跑 L3 加密 spec 前需先 generate;手动命令在 c4-encrypted-archive.spec.ts 注释里
- **Follow-up**:Docker Desktop kernel-lock 仍在;真实 `docker compose up` 验证待解决后回补
- **Follow-up**:生产部署前必须 env 覆盖 `SECRET_KEY` / `AUTH_SEED_ADMIN_PASSWORD`(C2 已记)
- ~~Follow-up:vite.config.ts test 字段类型错~~ 已 C4 顺手修复
- ~~Follow-up:auth-login.spec.ts 截图路径~~ 暂未处理(本次 C4 未触及该 spec,不影响)

---

## 4. 下次开工建议

**一句话交接**:
> C4 `file-upload` 已实施完,L1 130 / L2 101 / L3 12 = 243 全绿(C4 新增 L1 54 + L2 50 + L3 2 = 106 用例)。M2 进度 2/3。下一步 `/opsx:archive file-upload` 归档(自动 commit + 更新 handoff §5),然后 `/opsx:propose` 开 C5 `parser-pipeline`(LLM 文档角色识别 / 报价表识别 / 投标人身份信息提取 / SSE 进度回推)。

**可直接粘贴给 AI 作为新会话起点**:
```
继续 documentcheck 项目。M2 进度 2/3:C4 file-upload apply 完成,待归档。
下一步先 /opsx:archive file-upload(commit C4 全部改动 + handoff 同步),
然后 /opsx:propose 开 C5 parser-pipeline:
  - LLM 调 C4 已建的 8 个解析点(身份信息 / 文档角色分类 / 报价表 sheet+列识别)
  - 写 bid_documents.file_role / bidders.identity_info / price_parsing_rules
  - 状态机:bidder.parse_status: extracted → identified → priced
  - SSE 进度回推(C1 sse_demo 骨架可复用)
对应 docs/user-stories.md US-4.1~4.3;参考 docs/execution-plan.md §3 C5 小节。
请先读 docs/handoff.md 确认现状,然后 openspec-propose 为 C5 生成 artifacts。
tasks.md 按 CLAUDE.md OpenSpec 集成约定打标签。
```

**C5 前的预备条件(已就绪)**:

- `bidders.identity_info` JSONB 字段就位(C5 LLM 写)
- `bid_documents.file_role` 字段就位(C5 LLM 写;C4 阶段恒 NULL)
- `price_parsing_rules` 表 + `column_mapping` JSONB schema(`code_col / name_col / unit_col / qty_col / unit_price_col / total_price_col`)就位;C4 PUT 端点骨架可被 C5 LLM 直接调
- C1 LLM 适配层 `app/services/llm/` 单一接口已就位(dashscope/openai 二选一,timeout/retry 已封)
- C1 SSE 骨架 `/demo/sse` 仍在,C5 改造为 `/api/projects/{pid}/parse-progress` 即可
- `extract` 已写出 docx/xlsx 物理文件到 `extracted/<pid>/<bid>/<archive_hash>/`,C5 解析时直接 `Path()` 读
- L2 fixture `clean_users` 已清 4 张 C4 新表,C5 不需要再扩(除非引新表)

---

## 5. 最近变更历史(仅保留最近 5 条)

| 日期 | 变更 |
|---|---|
| 2026-04-14 | **C4 `file-upload` 实施完成(待归档,M2 进度 2/3)**:4 模型 + 0003 迁移 + upload/extract 服务 + 3 路由(bidders / documents / price)+ 6 前端组件 + ProjectDetailPage 重写;L1 130 / L2 101 / L3 12 = 243 pass;C4 新增 106 用例;关键决策:文件路径 absolute / GBK cp437 回路 / 加密包两阶段 probe |
| 2026-04-14 | **C3 `project-mgmt` 归档(M2 进度 1/3)**:Project 模型 + 软删 + 权限隔离 + 分页筛选搜索;L1 76 / L2 51 / L3 10 = 137 pass;C3 新增 72 用例;同步修订 user-stories.md US-2.4(硬删→软删)|
| 2026-04-14 | C3 `project-mgmt` propose 完成:4 artifact,7 Requirement + 30 Scenario;软删 vs 硬删冲突由用户拍板选 A 软删 |
| 2026-04-14 | **C2 `auth` 归档(M1 完成)**:L1/L2/L3 合计 65 pass 0 fail;JWT + 失败计数+锁定 + 强制改密(pwd_v 毫秒) + 路由守卫 + AuthContext + 前端 3 页面;M1 凭证 4 张截图 `e2e/artifacts/m1-demo-2026-04-14/` |
| 2026-04-14 | C2 `auth` propose 完成:4 artifact,7 Requirement + 22 Scenario;pwd_v 方案替 Redis 黑名单 |
