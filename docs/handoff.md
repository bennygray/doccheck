# 项目 Handoff

> **跨会话/跨人接手的现场视角快照。** 计划视角见 `docs/execution-plan.md` §5。
>
> 本文档职责:记录"现在人在哪、下一步干什么、有什么没说清"。
> 最近变更历史只保留 5 条,更早历史去 `git log` 查。

---

## 1. 当前状态快照

| 项 | 值 |
|---|---|
| 当前里程碑 | **M3 启动**,C6 `detect-framework` apply 完成,待归档 |
| 当前 change | C6 `detect-framework` apply 完成,待 archive(未 commit)|
| 当前任务行 | N/A |
| 最新 commit | C5 归档 `e3fda28` — C6 本次 archive commit 由用户发起 |
| 工作区 | C6 全量改动:backend **5 新模型**(agent_task / pair_comparison / overall_analysis / analysis_report / async_task)+ **0005 迁移** + **services/detect/{registry,context,engine,judge}.py** + **10 Agent 骨架**(7 pair + 3 global,dummy run)+ **services/async_tasks/{tracker,scanner}.py**(D3 通用任务表,消化 C4/C5 event loop 重启丢任务遗留)+ **4 端点**(POST start / GET status / GET events SSE / GET reports/{v})+ **7 schemas** + 改 projects.py 加 analysis 字段 + main.py lifespan scanner startup / cpu_executor shutdown + extract/content/llm_classifier 3 处 track 包裹;frontend **useDetectProgress / StartDetectButton / DetectProgressIndicator / ReportPage** + ProjectDetailPage 集成 DetectSection + App.tsx /reports 路由 + types/api 扩 ~10 类型 + 4 方法。**测试合计 361 全绿**(L1 188 / L2 173,其中 L3 沿 C5 降级手工凭证),C6 新增 **62 个用例**(L1 35 后端 + 14 前端 + L2 27 后端) |

---

## 2. 本次 session 关键决策(2026-04-14,C6 apply 阶段)

### propose 阶段已敲定(4 决策)

- **A1 整体做**:不拆 C6a/C6b,接受 ~13 Req / ~50 Scenario(实际 13 Req / 53 Scenario,与 C5 同量级)
- **B1 409 拒绝**:项目 analyzing 态再次启动检测 → 409 `{current_version, started_at}`,不做 resume/覆盖语义
- **C2 10 Agent 注册表 + dummy run**:name + agent_type(pair/global)+ preflight 三元组为稳定 contract;10 Agent 的 `run()` 全部走 dummy(sleep + 随机分);C7~C13 只改 `run()` 不动框架
- **D3 通用 async_tasks 表 + 只扫不自动恢复**:4 subtype 覆盖 extract / content_parse / llm_classify / agent_run;启动扫 stuck → 标 timeout + 实体状态回滚,不自动重调,用户手动重试(复用 C5 的 /re-parse / /start 端点)

### apply 阶段就地敲定

- **AGENT_TIMEOUT_S / GLOBAL_TIMEOUT_S 动态读取**:最初常量冻结在 import 期,L2 monkeypatch 无效;改为 `get_agent_timeout_s() / get_global_timeout_s()` 运行时读 env,保留向后兼容的模块常量
- **agents/__init__.py 在 analysis.py 中 `noqa: F401` import**:路由模块显式 import `app.services.detect.agents` 触发 10 个 @register_agent,否则 AGENT_REGISTRY 在 FastAPI 启动时未被填充
- **dummy_pair_run / dummy_global_run 共享 helper**:`agents/_dummy.py` 集中写入 PairComparison / OverallAnalysis 行,避免 10x boilerplate;C7~C13 真实 Agent 替换时删除
- **preflight 共享查询 helper**:`agents/_preflight_helpers.py` 封装 `bidder_has_role / bidder_has_metadata / bidder_has_priced / bidder_has_images / bidders_share_any_role`,C7+ 复用
- **L2 SSE 测试延 C5 precedent**:httpx ASGITransport 流不可靠断开 → 只覆盖 404 路径,流式语义靠 L1 broker + L3 手工验证
- **clean_users fixture 扩 5 表**:`async_tasks → analysis_reports → overall_analyses → pair_comparisons → agent_tasks`,按 FK 顺序前置
- **L3 沿 C5 降级手工凭证**:Docker Desktop kernel-lock 未解除,`e2e/artifacts/c6-2026-04-14/README.md` 占位 + 7 张截图计划
- **C4/C5 tracker 衔接**:extract_archive / extract_content / classify_bidder 三个入口函数分别包 `async with track()`;重启恢复由 scanner 统一处理;C5 报价规则(E3 已处理)不重复包裹
- **judge.py 铁证强制 ≥ 85**:`any(pc.is_ironclad) → total = max(total, 85.0)`,对齐 requirements §F-RP-01;LLM 结论字段留空 + 前端显示 "AI 综合研判暂不可用"(C14 接入真 LLM)
- **ProcessPoolExecutor 接口预留**:`get_cpu_executor()` lazy 单例,C6 dummy 不消费;FastAPI shutdown 调 `shutdown_cpu_executor()` 释放

### 文档联动

- **`backend/README.md`** 新增 "C6 detect-framework 依赖" 段:环境变量(AGENT_TIMEOUT_S / GLOBAL_TIMEOUT_S / ASYNC_TASK_HEARTBEAT_S / ASYNC_TASK_STUCK_THRESHOLD_S / INFRA_DISABLE_DETECT / INFRA_DISABLE_SCANNER)+ SSE 路径 + scanner 行为
- **`docs/handoff.md`** 即本次更新
- **不修订 user-stories**:实现与 US-5.1~5.4 描述一致;US-5.1 AC-5 "AgentTask C(n,2)×7+3" 精确落地

---

## 2.bak1 上一 session 决策(2026-04-14,C5 apply 阶段)

### propose 阶段已敲定(本次未变更)

- **A1 整体做**:不拆 C5a/C5b,接受 ~14 Req / ~45 Scenario(实际 13 Req / 50 Scenario)
- **B1 完整 SSE 事件流**:`/api/projects/{pid}/parse-progress` 推送 5 类业务事件 + heartbeat
- **C2 + β**:LLM 识别即自动 `confirmed=true` 立即批量回填;bidder 全 sheet 成功才 priced,部分失败 → price_partial
- **报价可选**:无报价表 bidder 终态 = identified,不必进 priced
- **D2 人工修正 a+b 做 c 降级**:前端 RoleDropdown + PriceRulesPanel 完整;角色关键词 Python 常量,管理员后台 UI 留 C17
- **E3 DB 原子占位**:`price_parsing_rules` partial unique index + asyncio.Event 快路径 + DB poll(3s × 5min)兜底

### apply 阶段就地敲定(D 级实施细节,见 design.md 9 条)

- **顺手吃 C4 follow-up**:HTTP 413/422 deprecated 常量名修(deprecation warning 清掉);C4 "event loop 重启丢任务"的报价规则那一半由 E3 DB 原子占位消化
- **0004 迁移在 SQLite 下退化**:partial unique index 仅 PostgreSQL 原生支持,SQLite 退化为普通索引(应用层保证唯一性,不影响测试)
- **extract → pipeline 衔接**:`extract/engine.py` 的 `_aggregate_bidder_status` 完成后 `await session.refresh(bidder)` 再 `trigger_pipeline(bidder_id)` —— 状态确实进 extracted 才触发,不会 partial / failed 时也调
- **role_classifier 漏返兜底**:LLM 给了部分 doc,剩下的走规则兜底(覆盖 spec "LLM 漏返"场景)
- **fill_price 数字归一化**:千分位 / 货币符号 / 科学计数 (regex `^-?\d+(\.\d+)?$`);中文大写金额本期不实现,字段写 NULL 不阻断行
- **L2 SSE 测试避坑**:httpx ASGITransport 下 `aiter_lines` 不能可靠摘除流(server 持续推 heartbeat 永不 EOF);L2 改为分层覆盖(broker / build_snapshot / format_sse 单独验 + 端点 404 走 HTTP 客户端)
- **L3 整体降级手工**:LLM 内部协程 Playwright 无法 page.route 拦截 + Docker Desktop kernel-lock 阻塞真启动;凭证 README 占位在 `e2e/artifacts/c5-2026-04-14/`,等 kernel-lock 解除后手工补 7 张截图
- **clean_users fixture 扩 4 张表**:price_items / document_image / document_metadata / document_text 按 FK 顺序前置插入清理(C4 模式延伸)
- **`bidder.parse_status` 13 态**:C4 6 态 + C5 7 态(identifying/identified/identify_failed/pricing/priced/price_partial/price_failed),应用层枚举不加 DB CHECK

### 文档联动

- **`backend/README.md`** 新增 "C5 parser-pipeline 依赖" 段(LLM env vars + Pillow libjpeg + nginx SSE 配置 + INFRA_DISABLE_PIPELINE 测试环境变量)
- **`docs/handoff.md`** 即本次更新;execution-plan.md 暂未追加 §6 计划变更行(本次未调整粒度/顺序,仅落地 C5 既定计划)
- **不修订 user-stories**:实现与 US-4.2/4.3/4.4 描述一致;US-4.3 AC-7 "管理员维护关键词"在 spec 内显式标 "C17 升级"

---

## 2.bak 上一 session 决策(2026-04-14,C4 apply 阶段)

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

## 3. 待确认 / 阻塞

- 无硬阻塞,**M3 启动**,C6 已实施完,待 archive。
- **Follow-up(C6 新增)**:**L3 整体降级手工凭证待补**(延续 C5):Docker Desktop kernel-lock 解除后,按 `e2e/artifacts/c6-2026-04-14/README.md` 步骤跑 demo 并补 7 张截图。本次 L1+L2 = 361 用例已覆盖所有 spec scenario,L3 凭证仅作 M3 demo 价值
- **Follow-up(C6 新增)**:`judge.py` `DIMENSION_WEIGHTS` 是占位值(等权 + 铁证维度略高),C14 接入真实 LLM 综合研判时可调权重
- **Follow-up(C6 新增)**:10 Agent 的 `run()` 全部 dummy(0.2~1.0s sleep + 随机分),C7~C13 各 change 逐个替换真实实现;preflight / 注册 key / 签名保持不变
- **Follow-up(C6 新增)**:`ProcessPoolExecutor` 接口预留但 C6 dummy 不消费;C7 第一个 CPU 密集 Agent 实施时需调 `get_cpu_executor()` + 验证 max_workers 默认值在容器环境(cgroup 限制)是否合理
- ~~Follow-up(C4 留下,C5 部分消化):`asyncio.create_task` event loop 重启丢任务~~ **C6 D3 完全消化**:通用 `async_tasks` 表 + scanner 启动扫 stuck 覆盖 extract / content_parse / llm_classify / agent_run 四类;报价规则那一半(E3)维持不变
- **Follow-up(C4 留下)**:加密包 3 次密码错冻结(原 D2 决策推到 C17)
- **Follow-up(C4 留下)**:`e2e/fixtures/encrypted-sample.7z`(250 字节)未入库,CI 跑 L3 加密 spec 前需手动 generate
- **Follow-up**:Docker Desktop kernel-lock — 影响 `docker compose up` 真实部署验证 + L3 命令验证(C3/C4/C5/C6 spec 都跑不起来,Windows 10 + WSL2 内核锁定)
- **Follow-up**:生产部署前必须 env 覆盖 `SECRET_KEY` / `AUTH_SEED_ADMIN_PASSWORD`(C2 已记);C5 `LLM_API_KEY` 等;C6 无新 env 但调优可用 `AGENT_TIMEOUT_S / GLOBAL_TIMEOUT_S / ASYNC_TASK_HEARTBEAT_S / ASYNC_TASK_STUCK_THRESHOLD_S`
- **Follow-up(C5 留下)**:`role_keywords.py` Python 常量;C17 admin 后台搭起来后迁移到 DB + admin UI(D2 决策原约定)

---

## 4. 下次开工建议

**一句话交接**:
> **C6 `detect-framework` 已实施完,M3 启动**。L1 188 / L2 173 = **361 全绿**,C6 新增 62 用例;L3 延续 C5 降级手工凭证。下一步 `git commit`(message `归档 change: detect-framework(M3)`)+ `git push`,然后进 M3 下一个 change `/opsx:propose` 开 **C7 `detect-agent-text-similarity`**(第一个真实 Agent 实现:整文档级文本相似度,LLM + 本地向量兜底)。

**可直接粘贴给 AI 作为新会话起点**:
```
继续 documentcheck 项目。M3 启动,C6 detect-framework 已 apply + archive(待 user commit)。
下一步进 C7 /opsx:propose detect-agent-text-similarity:
  - 替换 app/services/detect/agents/text_similarity.py 的 run() 为真实实现
  - LLM 调用(prompt 见 requirements §10.8 L-1)+ 本地向量兜底
  - 不动框架:registry / preflight / engine / judge 保持不变
  - 覆盖 US-5.2 "text_similarity" 维度的真实 AC
对应 docs/execution-plan.md §3 C7 小节。
请先读 docs/handoff.md 确认现状,然后 openspec-propose 为 C7 生成 artifacts。
```

**C7 前的预备条件(已就绪)**:

- **Agent 注册表 + preflight 骨架**(C6)稳定;C7 只改 `agents/text_similarity.py` 的 `run()` 函数
- **AgentContext.llm_provider 接口**已预留,C7 真实 Agent 消费;C6 dummy 传 None
- **PairComparison / OverallAnalysis 表**已建,C7 直接写行
- **LLM 适配层**(C1 / C5 ScriptedLLMProvider)可复用;需在 `llm_mock.py` 加 `mock_llm_text_similarity_success / mock_llm_text_similarity_bad_json` 2 fixture
- **clean_users fixture** 已清 13 张表(含 C6 5 张),C7 不引新表不用扩
- **INFRA_DISABLE_DETECT=1** 测试开关可复用(C7 测真实 run 时 unset)

---

## 5. 最近变更历史(仅保留最近 5 条)

| 日期 | 变更 |
|---|---|
| 2026-04-14 | **C6 `detect-framework` 实施完成(待归档,M3 启动)**:5 模型 + 0005 迁移 + services/detect/{registry,context,engine,judge}.py + 10 Agent 骨架(7 pair + 3 global,dummy run)+ services/async_tasks/{tracker,scanner}.py + 4 端点(POST start / GET status / GET events SSE / GET reports/{v})+ 4 前端组件(useDetectProgress / StartDetectButton / DetectProgressIndicator / ReportPage)+ App 路由 /reports;**L1 188 / L2 173 = 361 pass**;C6 新增 62 用例;关键决策:A1 整体 / B1 409 拒绝 / C2 10 Agent 注册表 + dummy run / D3 通用 async_tasks 表 + 只扫不自动恢复(消化 C4/C5 遗留);L3 延续 C5 降级手工凭证 |
| 2026-04-14 | **C5 `parser-pipeline` 归档(M2 完成 3/3,commit e3fda28)**:4 模型 + 0004 迁移 + parser/{content,llm,pipeline} 12 模块 + 4 端点 + 4 前端组件;L1 153 / L2 143 = 296 pass;C5 新增 53 用例;关键决策:E3 DB 原子占位 / C2β 自动 confirmed + β 终态 / D2 关键词常量 / SSE 内存 broker |
| 2026-04-14 | **C4 `file-upload` 归档(M2 进度 2/3)**:4 模型 + 0003 迁移 + upload/extract 服务 + 3 路由 + 6 前端组件;L1 130 / L2 101 / L3 12 = 243 pass;C4 新增 106 用例;关键决策:文件路径 absolute / GBK cp437 回路 / 加密包两阶段 probe |
| 2026-04-14 | **C3 `project-mgmt` 归档(M2 进度 1/3)**:Project 模型 + 软删 + 权限隔离 + 分页筛选搜索;L1 76 / L2 51 / L3 10 = 137 pass;C3 新增 72 用例;同步修订 user-stories.md US-2.4(硬删→软删)|
| 2026-04-14 | **C2 `auth` 归档(M1 完成)**:L1/L2/L3 合计 65 pass 0 fail;JWT + 失败计数+锁定 + 强制改密(pwd_v 毫秒) + 路由守卫 + AuthContext + 前端 3 页面;M1 凭证 4 张截图 `e2e/artifacts/m1-demo-2026-04-14/` |
