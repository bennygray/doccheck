# 项目 Handoff

> **跨会话/跨人接手的现场视角快照。** 计划视角见 `docs/execution-plan.md` §5。
>
> 本文档职责:记录"现在人在哪、下一步干什么、有什么没说清"。
> 最近变更历史只保留 5 条,更早历史去 `git log` 查。

---

## 1. 当前状态快照

| 项 | 值 |
|---|---|
| 当前里程碑 | **M3 进行中(2/9)**,C7 `detect-agent-text-similarity` 已 archive,待 commit |
| 当前 change | C7 已 archive,即将随本次 commit 一起提交 |
| 当前任务行 | N/A |
| 最新 commit | C6 归档 `999c0d6` — C7 archive commit 即将产生 |
| 工作区 | C7 全量改动:**新增 `backend/app/services/detect/agents/text_sim_impl/` 子包 7 文件**(config/stopwords/models/segmenter/tfidf/llm_judge/aggregator)+ **重写 `agents/text_similarity.py::run()`** 为真实双轨算法(本地 TF-IDF+cosine 筛段落对 → LLM 定性 template/generic/plagiarism → 汇总 score + is_ironclad)+ `engine.py::_build_ctx` 注入 LLM provider(C6 Q2a 实施期落地,ruff auto-fix 顺带 datetime UTC + TimeoutError)+ `tests/fixtures/llm_mock.py` 新增 3 fixture+1 工厂 + **L1 5 test 文件 42 用例**(`tests/unit/services/detect/agents/text_sim_impl/test_{segmenter,tfidf,llm_judge,aggregator}.py` + `test_text_similarity_run.py`)+ `test_detect_preflight.py` 追加 3 用例(超短 skip / no shared role / ok) + **L2 1 test 文件 5 scenario**(`tests/e2e/test_detect_text_similarity.py` 覆盖 execution-plan §3 C7 全 5 场景) + `backend/README.md` 新增 "C7 依赖" 段(3 env) + `e2e/artifacts/c7-2026-04-15/README.md` L3 手工凭证占位 + `openspec/specs/detect-framework/spec.md` sync(+5 Req / +15 Scenario,24 Req / 72 Scenario 总)。**测试合计 410 全绿**(L1 232 / L2 178,L3 延续手工凭证),C7 新增 **49 个用例**(L1 44 + L2 5) |

---

## 2. 本次 session 关键决策(2026-04-15,C7 apply+archive)

### propose 阶段已敲定(4 决策)

- **A1 双轨分工**:本地 TF-IDF 始终跑(切段+算分+筛超阈值对)+ LLM 定性 template/generic/plagiarism;LLM 失败 → 仅程序分数 + "AI 研判暂不可用"。对齐 requirements §10.8 L-4 原文;execution-plan 场景 5 "LLM 不可用 → 退化本地向量" 天然落进 A1 的 LLM 失败分支
- **B1 零新增依赖**:复用 C5 已装的 `jieba + scikit-learn + numpy`,不引 sentence-transformers/torch(1.5GB 安装量过重,首次下模型需网络)
- **C 段落切 + 短段合并 + 超短 skip**:docx 原生段落(body 位置,页眉页脚排除对齐 US-4.2 AC-3);< 50 字相邻合并;单侧 < `TEXT_SIM_MIN_DOC_CHARS`(500)→ preflight skip "文档过短无法对比"
- **D 不加缓存**:一轮检测内 pair 不重复;版本+1 重检全量重跑(C14 综合研判必然变)。简单正确优先

### apply 阶段就地敲定

- **`TfidfVectorizer(max_df=0.95)` 短样本灾难,改 `max_df=1.0`**:2 段相同文档时每 token 100% 频率 → 全部超 0.95 被过滤 → vocab 空 → 返 []。STOPWORDS + 单字过滤已处理过高频词,无需 max_df 二次过滤;L1 test 跑红后就地修正
- **`role_keywords.py` 是英文标识符**(technical/construction/bid_letter/...)不是中文"技术方案",design D1 错写了中文角色名,apply 期对正;segmenter `ROLE_PRIORITY` = technical → construction → bid_letter → company_intro → other,跳过 pricing/unit_price/qualification/authorization(数字或定型文书,对文本相似度无区分力)
- **executor cancel 无法真中断(C6 Risk-1 具体化)**:ProcessPoolExecutor 子进程任务 submit 后不可 cancel;C7 缓解:`max_features=20000 + MAX_PAIRS=30` 保证单次 executor < 30s,5min agent timeout 余量大;彻底解(Process.kill)留更后 change
- **`engine._build_ctx` llm_provider 注入走 `get_llm_provider()` + try/except fallback None**:C6 Q2a 落地方式;LLM 未配置(无 API key)时 provider=None,Agent 自然进降级,不 crash
- **L2 测试手动构造 ctx 直调 Agent.run()**,不走 engine.run_detection:绕开 track/超时/SSE broker,测试更快更稳,5 scenario < 5s 跑完
- **`max_df=1.0` 决策文档**:design D2 written-time 是 0.95,apply 期修订记录在 tasks.md 3.2 备注

### 文档联动

- **`backend/README.md`** 新增 "C7 detect-agent-text-similarity 依赖" 段:3 env(`TEXT_SIM_MIN_DOC_CHARS` 500 / `TEXT_SIM_PAIR_SCORE_THRESHOLD` 0.70 / `TEXT_SIM_MAX_PAIRS_TO_LLM` 30)+ jieba 首启延迟说明 + 容器 cpu_count 验证命令
- **`openspec/specs/detect-framework/spec.md`** sync(sync-specs skill):+5 Req(双轨算法 / 超短 preflight / LLM 降级 / evidence_json / executor 消费)+ 15 Scenario;MODIFIED "10 Agent 骨架" 的 dummy scenario 改 section_similarity(text_similarity 不再 dummy)
- **`docs/handoff.md`** 即本次更新

---

## 2.bak1 上一 session 决策(2026-04-14,C6 apply 阶段)

### propose 阶段已敲定(本次未变更)

- **A1 整体做**:不拆 C6a/C6b,接受 ~13 Req / ~50 Scenario(实际 13 Req / 53 Scenario,与 C5 同量级)
- **B1 409 拒绝**:项目 analyzing 态再次启动检测 → 409 `{current_version, started_at}`,不做 resume/覆盖语义
- **C2 10 Agent 注册表 + dummy run**:name + agent_type(pair/global)+ preflight 三元组为稳定 contract;10 Agent 的 `run()` 全部走 dummy(sleep + 随机分);C7~C13 只改 `run()` 不动框架
- **D3 通用 async_tasks 表 + 只扫不自动恢复**:4 subtype 覆盖 extract / content_parse / llm_classify / agent_run;启动扫 stuck → 标 timeout + 实体状态回滚,不自动重调,用户手动重试(复用 C5 的 /re-parse / /start 端点)

### apply 阶段就地敲定

- **AGENT_TIMEOUT_S / GLOBAL_TIMEOUT_S 动态读取**:最初常量冻结在 import 期,L2 monkeypatch 无效;改为 `get_agent_timeout_s() / get_global_timeout_s()` 运行时读 env,保留向后兼容的模块常量
- **agents/__init__.py 在 analysis.py 中 `noqa: F401` import**:路由模块显式 import `app.services.detect.agents` 触发 10 个 @register_agent,否则 AGENT_REGISTRY 在 FastAPI 启动时未被填充
- **dummy_pair_run / dummy_global_run 共享 helper**:`agents/_dummy.py` 集中写入 PairComparison / OverallAnalysis 行,避免 10x boilerplate;C7~C13 真实 Agent 替换时删除(C7 已使 text_similarity 脱离 _dummy,文件仍保留给 9 Agent)
- **preflight 共享查询 helper**:`agents/_preflight_helpers.py` 封装 `bidder_has_role / bidder_has_metadata / bidder_has_priced / bidder_has_images / bidders_share_any_role`,C7+ 复用(C7 preflight 用了 `segmenter.choose_shared_role` 替代 `bidders_share_any_role`,因需要 role 优先级排序)
- **L2 SSE 测试延 C5 precedent**:httpx ASGITransport 流不可靠断开 → 只覆盖 404 路径,流式语义靠 L1 broker + L3 手工验证
- **clean_users fixture 扩 5 表**:`async_tasks → analysis_reports → overall_analyses → pair_comparisons → agent_tasks`,按 FK 顺序前置
- **L3 沿 C5 降级手工凭证**:Docker Desktop kernel-lock 未解除,`e2e/artifacts/c6-2026-04-14/README.md` 占位 + 7 张截图计划
- **C4/C5 tracker 衔接**:extract_archive / extract_content / classify_bidder 三个入口函数分别包 `async with track()`;重启恢复由 scanner 统一处理;C5 报价规则(E3 已处理)不重复包裹
- **judge.py 铁证强制 ≥ 85**:`any(pc.is_ironclad) → total = max(total, 85.0)`,对齐 requirements §F-RP-01;LLM 结论字段留空 + 前端显示 "AI 综合研判暂不可用"(C14 接入真 LLM)
- **ProcessPoolExecutor 接口预留**:`get_cpu_executor()` lazy 单例,C6 dummy 不消费;FastAPI shutdown 调 `shutdown_cpu_executor()` 释放(**C7 已消费**:text_similarity 的 TF-IDF + cosine 矩阵计算)

---

## 2.bak2 上上 session 决策(2026-04-14,C5 apply 阶段)

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

---

## 3. 待确认 / 阻塞

- 无硬阻塞,**M3 进度 2/9**,C7 已 archive,本次 commit 后继续 C8
- **Follow-up(C7 新增)**:**L3 手工凭证待补**(延续 C5/C6):Docker Desktop kernel-lock 解除后,按 `e2e/artifacts/c7-2026-04-15/README.md` 步骤跑 3 张截图(启动检测 / 报告页 text_similarity 真实分数 + 铁证徽章 / evidence samples 展开)
- **Follow-up(C7 新增)**:`ProcessPoolExecutor` executor cancel 无法真中断子进程任务(C6 Risk-1 继承)— C7 用 `max_features + MAX_PAIRS` 限时缓解;彻底解(Process.kill + 超时守护)留 C15/C16 或独立 follow-up
- **Follow-up(C7 新增)**:容器 `cpu_count` 验证(C6 Q3 继承)— kernel-lock 解除后跑 `docker exec backend python -c "import os; print(os.cpu_count())"`,若显著超实际限额开独立 follow-up(可能需读 cgroup)
- **Follow-up(C6 留下,C7 消化 1/10)**:10 Agent 的真实 `run()` 替换 — C7 已完成 text_similarity,剩 9 个(section_similarity / structure_similarity / metadata_author/time/machine / price_consistency / error_consistency / style / image_reuse)待 C8~C13 逐个替换
- **Follow-up(C6 留下)**:`judge.py` `DIMENSION_WEIGHTS` 是占位值(等权 + 铁证维度略高),C14 接入真实 LLM 综合研判时可调权重
- **Follow-up(C4 留下)**:加密包 3 次密码错冻结(原 D2 决策推到 C17)
- **Follow-up(C4 留下)**:`e2e/fixtures/encrypted-sample.7z`(250 字节)未入库,CI 跑 L3 加密 spec 前需手动 generate
- **Follow-up**:Docker Desktop kernel-lock — 影响 `docker compose up` 真实部署验证 + L3 命令验证(C3~C7 spec 都跑不起来,Windows 10 + WSL2 内核锁定)
- **Follow-up**:生产部署前必须 env 覆盖 `SECRET_KEY` / `AUTH_SEED_ADMIN_PASSWORD`(C2 已记);C5 `LLM_API_KEY` 等;C6 调优 `AGENT_TIMEOUT_S / GLOBAL_TIMEOUT_S / ASYNC_TASK_HEARTBEAT_S / ASYNC_TASK_STUCK_THRESHOLD_S`;C7 调优 `TEXT_SIM_MIN_DOC_CHARS / _PAIR_SCORE_THRESHOLD / _MAX_PAIRS_TO_LLM`
- **Follow-up(C5 留下)**:`role_keywords.py` Python 常量;C17 admin 后台搭起来后迁移到 DB + admin UI(D2 决策原约定)

---

## 4. 下次开工建议

**一句话交接**:
> **C7 `detect-agent-text-similarity` 已归档,M3 进度 2/9**。L1 232 / L2 178 = **410 全绿**,C7 新增 49 用例;L3 延续 C5/C6 降级手工凭证。下一步 `git push`(本次 archive commit 已产生),然后进 M3 下一个 change `/opsx:propose` 开 **C8 `detect-agent-section-similarity`**(第二个真实 Agent:章节级相似度,按标题切章对比;章节切分失败降级到整文档粒度与 C7 结果合并去重)。

**可直接粘贴给 AI 作为新会话起点**:
```
继续 documentcheck 项目。M3 进度 2/9,C7 detect-agent-text-similarity 已 archive + commit。
下一步进 C8 /opsx:propose detect-agent-section-similarity:
  - 替换 app/services/detect/agents/section_similarity.py 的 run() 为真实实现
  - 按标题切章 + 章节级 TF-IDF / cosine(可能复用 C7 text_sim_impl 的 tfidf 模块)
  - 兜底:章节切分失败 → 降级为整文档粒度与 C7 结果合并去重
  - 不动框架:registry / preflight / engine / judge 保持不变
  - 覆盖 execution-plan §3 C8 的 4 scenario
对应 docs/execution-plan.md §3 C8 小节。
请先读 docs/handoff.md 确认现状,然后 openspec-propose 为 C8 生成 artifacts。
```

**C8 前的预备条件(已就绪)**:

- **C7 `text_sim_impl` 模块可复用**:`tfidf.compute_pair_similarity`(纯函数,可 pickle 进 executor)和 `aggregator`(score 汇总 + is_ironclad + evidence_json)可直接被 C8 import;`segmenter` 需要扩一个"章节级"切分函数(新函数,不改原 `load_paragraphs_for_roles`)
- **LLM mock 工厂**:`make_text_similarity_response` 可被 C8 重用或另起 `make_section_similarity_response`(同 JSON schema)
- **`PairComparison.dimension` 枚举**:已支持任意字符串,C8 写 `"section_similarity"` 即可;judge.py 的 `DIMENSION_WEIGHTS` 已含该 key
- **title 切分起点**:C5 DocumentText 按 `paragraph_index` 有顺序,但无 `style/heading_level` 字段。C8 起点:用正则识别"第X章 / 第X节 / 一、二、/ 1. 2. / 数字+标题"模式切章;识别失败的文档整个归为 "章节切分失败" bucket(降级处理)
- **L3 延续降级手工凭证**:Docker kernel-lock 未解除,模式不变

---

## 5. 最近变更历史(仅保留最近 5 条)

| 日期 | 变更 |
|---|---|
| 2026-04-15 | **C7 `detect-agent-text-similarity` 归档(M3 进度 2/9)**:新增 `text_sim_impl/` 7 文件(config/stopwords/models/segmenter/tfidf/llm_judge/aggregator)+ 重写 `text_similarity.py::run()` 为真实双轨算法(本地 TF-IDF+cosine 筛 → LLM 定性 template/generic/plagiarism → score 汇总 + is_ironclad)+ `engine._build_ctx` 注入 LLM provider;**L1 232 / L2 178 = 410 pass**;C7 新增 49 用例;零新增第三方依赖(jieba/sklearn/numpy 复用 C5);关键决策:A1 双轨分工 / B1 零新增依赖 / `max_df=1.0` 抗短样本 / role_keywords 英文标识符;spec sync +5 Req+15 Scenario;L3 延续手工凭证 |
| 2026-04-14 | **C6 `detect-framework` 归档(M3 启动,commit 999c0d6)**:5 模型 + 0005 迁移 + services/detect/{registry,context,engine,judge}.py + 10 Agent 骨架(dummy run)+ services/async_tasks/{tracker,scanner}.py + 4 端点(POST start / GET status / GET events SSE / GET reports/{v})+ 4 前端组件 + /reports 路由;L1 188 / L2 173 = 361 pass;C6 新增 62 用例;关键决策:A1 整体 / B1 409 拒绝 / C2 10 Agent 注册表 dummy / D3 通用 async_tasks 表 + 只扫不恢复 |
| 2026-04-14 | **C5 `parser-pipeline` 归档(M2 完成 3/3,commit e3fda28)**:4 模型 + 0004 迁移 + parser/{content,llm,pipeline} 12 模块 + 4 端点 + 4 前端组件;L1 153 / L2 143 = 296 pass;C5 新增 53 用例;关键决策:E3 DB 原子占位 / C2β 自动 confirmed + β 终态 / D2 关键词常量 / SSE 内存 broker |
| 2026-04-14 | **C4 `file-upload` 归档(M2 进度 2/3)**:4 模型 + 0003 迁移 + upload/extract 服务 + 3 路由 + 6 前端组件;L1 130 / L2 101 / L3 12 = 243 pass;C4 新增 106 用例;关键决策:文件路径 absolute / GBK cp437 回路 / 加密包两阶段 probe |
| 2026-04-14 | **C3 `project-mgmt` 归档(M2 进度 1/3)**:Project 模型 + 软删 + 权限隔离 + 分页筛选搜索;L1 76 / L2 51 / L3 10 = 137 pass;C3 新增 72 用例;同步修订 user-stories.md US-2.4(硬删→软删)|
