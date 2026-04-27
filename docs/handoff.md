# 项目 Handoff

> **跨会话/跨人接手的现场视角快照。** 计划视角见 `docs/execution-plan.md` §5。
>
> 本文档职责:记录"现在人在哪、下一步干什么、有什么没说清"。
> 最近变更历史只保留 5 条,更早历史去 `git log` 查。

---

## 1. 当前状态快照

| 项 | 值 |
|---|---|
| 当前里程碑 | **M4 完成 + V1 全量验收 + admin-llm-config + fix-mac-packed-zip-parsing + honest-detection-results + harden-async-infra + agent-skipped-error-guard + llm-classifier-observability + test-infra-followup-wave2 + fix-admin-users-page-flaky-test + config-llm-timeout-default(CH-3)+ parser-accuracy-fixes(CH-1)+ detect-template-exclusion(CH-2)+ fix-llm-timeout-default-followup + fix-section-similarity-spawn-loop + fix-bug-triple-and-direction-high(2026-04-27 归档)** |
| 当前 change | `fix-bug-triple-and-direction-high` **归档完成**(2026-04-27)。修 3 个用户报告 bug + 9 个同根因对称性盲点("半成品契约":input 字段定义但 detect 不消费 / SSE 协议 publish 漏字段 / 算法维度对齐错位)。**4 轮 reviewer 35+ HIGH 全部吸收** — v1→v4 三次"补丁式修订"被找出 24 HIGH(scorer 数学不支持 ironclad / amount_pattern 维度错配 / lift hook 漏 prop chain / watchdog 阈值 < heartbeat 等),v4 self-review 后转向 happy-path 数据流第一性倒推。代码:**A 后端 SSE 协议**(judge.py:489 publish project_status_changed MUST 早于 report_ready / engine.py:135 crash 路径 publish + status=ready / scanner.py:174 回滚也 publish);**B 前端 hook lift**(useDetectProgress 从 HeroDetectArea 子组件提到 ProjectDetailPage 父 + props chain;hook 初值 "draft"→null + Tag `??` 区分;watchdog 35s 业务事件 lastBizEventAt 不算 heartbeat;DetectEventType union 加 project_status_changed/error;useParseProgress 同款 dead listener 修复);**C/D 2 个新 global Agent**(price_total_match 任意两家 total 完全相等 → has_iron_evidence;price_overshoot 任一超限 → has_iron_evidence,max_price=NULL/≤0 skip);**E 权重重平衡**(error_consistency 0.12→0.10 / style 0.08→0.07 / image_reuse 0.05→0.02 释放 0.06 给 2 新维度各 0.03,和=1.00);**F UI**(DIMENSION_LABELS+SHORT 加 2 维 + AdminRulesPage label "报价天花板"→"异常低价偏离" 修语义错位 + DimensionRow 既有 is_ironclad Tag 自动适配);**G 11→13 维巡检**(test_detect_judge / test_detect_registry / test_rules_mapper / test_export_generator / test_reports_api / e2e task_count 11→13/25→27 + judge_llm.py prompt + 前端 6 处 11 维注释 + EXPECTED_AGENT_COUNT 11→13 + admin-rules spec dimensions 10→12)。spec delta 3 capability:project-status-sync MODIFY 既有 SSE Requirement 加 3 scenarios(detect 完成 + crash + scanner) / detect-framework ADD 2 Requirement(price_overshoot + price_total_match) / admin-rules MODIFY Get rules config API(10→12)。L1 **1182/8 skipped**(原 1166 + 新 16);L2 **286/2 skipped**(11→13 task_count 修订 + judge_llm e2e fixture 加 2 新 OA);前端 typecheck ✅;**L3 降级 manual + 凭证**(`e2e/artifacts/fix-bug-triple-and-direction-high-2026-04-27/`);Manual 真实 e2e 留 follow-up(L1+L2 已锁根因) |
| 先前 change | `fix-section-similarity-spawn-loop` **2026-04-26 归档完成**(commit d63a66f)。性能修复:`section_sim_impl/scorer.py` 把对 N 个章节对的 `for cp in chapter_pairs: await run_isolated(...)` 循环改成**一次** `run_isolated(compute_all_pair_sims_batch, ...)`,N 次 spawn 变 1 次 spawn,固定开销(spawn ~230ms + jieba 词典冷启动 ~600ms + numpy/sklearn import + IPC)从 O(N) 降到 O(1)。微基准:per-pair 路径 3.0s/对 × N=80 = 240s 撞 300s 阈值;批量化后 single-spawn ~7s + N×7ms,N=80 时 ~55s;真实数据更狠 — manual e2e 实测 N=151/151/**408** 章节对(此前 e2e 三对 100% timeout 卡 300s 阈值),修后 elapsed=44s/139s/93s **全 succeeded**,N=408 走 93s = **13x 加速**;有 1 对铁证命中"3 段抄袭/408 对齐章节" score=56.57。代码:`scorer.py` 加 module-level `compute_all_pair_sims_batch` helper(必须 module-level — pickle by name)+ for 循环替换为单次 batch 调用 + 空 chapter_pairs short-circuit + import 移到顶部。spec delta:MODIFIED `pipeline-error-handling` Requirement "ProcessPool per-task 进程隔离" 加 2 scenario(批量化契约 + 批量超时走 skipped)。L1 **1166/8 skipped**(新增 3 case:核心契约 run_isolated 调用次数=1 防回归 + 批量 vs 单调结果一致性 + 空边界);L2 **286/2 skipped**;L3 不跑;凭证 `e2e/artifacts/fix-section-similarity-spawn-loop-2026-04-26/`(README + agent_tasks_after.json)。**新一轮 v3 检测 25 ✅/0 timeout 总分 92/高危**(此前 v2 是 22/3 timeout 总分 88/高危),围标信号回归更全面 |
| 先前 change | `fix-llm-timeout-default-followup` **2026-04-26 归档完成**(commit 386d0e7)。补 archive `config-llm-timeout-default` 漏的同步迁移:那次 change 改了 `llm_call_timeout`(cap)默认 60→300,但 factory 实际生效路径是 `min(per_call=llm_timeout_s, cap)`,per-call 默认还是 30 → 改 cap 等于不改,生产/开发部署零行为变化。本次 e2e 实测 3 供应商 zip 暴露:price_rule_detector LLM 60s 超时 → `price_parsing_rules.status='failed'` → 3 bidder 全 `price_failed` → 报价 3 维度被 skip。修法:`Settings.llm_timeout_s` 默认 30→300(与 cap 对齐) + 同步 `.env.example` / `docker-compose.yml::LLM_TIMEOUT_S:-30→300` / 删本机 `.env` 里 `LLM_TIMEOUT_S=60` 行 + L1 加 2 case 钉 per-call 默认 300。**Manual e2e**:re-parse + 重检测后 v1(5/低危/17✅/4skip/4timeout)→ v2(88/高危/22✅/3timeout/0skipped),报价 3 维度全跑通 + 原本 LLM 超时的 text_similarity(83.75)/ style(74)也跑出来了。属 CLAUDE.md "孤立改配置" 例外;L1 1163/8;L2 286/2;凭证 `e2e/artifacts/fix-llm-timeout-default-followup-2026-04-26/` |
| 先前 change | `detect-template-exclusion` **2026-04-25 归档完成**(commit 868d1ac)。CH-2(B 方案 3-change 拆分最后一个) **apply + L1/L2 + 前端 L1 全绿 + L3 手工凭证降级**(真 LLM golden 后续按需补,不阻塞归档)。解决 P0-4 模板假阳:3 家供应商用招标方下发的同一 docx 模板(metadata `author=LP + doc_created_at=2023-10-09 07:16` 三家一致)→ multi-dim 雪崩假阳(structure=100/iron / metadata_author=100/iron / metadata_time=100/iron / style=76.5 / text=57~91)→ formula_total≥85 铁证升级 → high。**Q1=A**(metadata 簇识别 + 维度剔除/降权),**Q2=删 D 兜底**(数学不可达 + A 已覆盖)。**Q3=A 保持** `template_cluster_detected=len(adjustments)>0` 语义。**Q4=做减法 M3**(spec 6 步顺序+行号下沉 design,只留语义 invariant)。spec delta:detect-framework ADD 2 Req(模板簇识别 / 维度剔除/降权与铁证抑制)+ MOD 1 Req(证据不足判定规则,扩 adjusted_pcs/adjusted_oas kwarg + 分母切 OA);**8 轮 reviewer**(round1 6H / round2 3H / round3-1 3H / round3-2 1H / round4 2H / round5 1H / round6 0H / round7 1H / round8 3H+5M)全部吸收 — 从 over-spec 收手做减法保持核心 invariant 4 条。代码:`models/analysis_report.py` 加 2 字段 + alembic 0012;新 `services/detect/template_cluster.py`(`_detect_template_cluster` + `_apply_template_adjustments` 双 dict 不回写 DB + DEF-OA OA.id 同步覆盖);`judge.py` 6 步顺序改造(两次 `_compute_dims_and_iron`:第一次 raw 给 DEF-OA 写库 / 第二次 adjusted 给 final_total);`judge_llm.py` 加 helper kwarg(`_has_sufficient_evidence` + `summarize` + `_is_pc/oa_ironclad` + `_run_l9` 透传);author 复用 `nfkc_casefold_strip` 与 metadata_author 语义对齐;file_role 限 `{technical,construction,bid_letter,company_intro,authorization,pricing,unit_price}`(VALID_ROLES 对齐);`compute_report` 签名/语义保持不变(主 spec L268+L2843 契约 + 2 条 L1 signature_unchanged)。L1 **1161 绿**(原 1115 + 新 46);L2 **286 绿**(原 281 + 5 新 case);前端 L1 **114 绿**;**L3 手工凭证降级** `e2e/artifacts/detect-template-exclusion-2026-04-25/README.md`(0 UI 改动 + L1/L2 全绿,符合 CLAUDE.md "L3 flaky 降级"条款);**真 LLM golden 待用户授权跑**(tasks 6.1/6.2 [manual],3 供应商 zip ~¥1 + 5-10 分钟)|
| 先前 change | `parser-accuracy-fixes` 归档完成。CH-1(B 方案 3-change 拆分第 2 个,跟 CH-3 → CH-1 → CH-2 顺序):6 项 parser 层精度修复 + `PriceParsingRule` **BREAKING** schema(column_mapping 单 mapping → **sheets_config 多 sheet 数组**)+ alembic 0011 兼容 migration。具体:**P0-1** identity_validator(LLM + 规则双保险,规则覆盖走 mismatch / LLM 空规则命中走 "fill" 补齐不降级,H1 review 修)**P0-3** `_parse_decimal` 扩 "元/万元/万" 后缀归一(B 家"￥486000元"→486000.00) **P1-5** 多 sheet 候选 + schema 改(sheets_config JSONB array,老 3 列 nullable + 同步回写做 backward compat,H2 review 修 + subprocess alembic 测试)**P1-6** 备注长文本行过滤(扫三 text 字段任一 ≥100 字 + 其他全空)**+ review M1** "备注:" sentinel 短词前缀 skip **P1-7** item_code 纯数字序号列置空 **P2-8** docx textbox 改 `lxml.etree.XPath` 预编译绕过 `python-docx.BaseOxmlElement.xpath(namespaces=...)` 已废 kwarg + **review H3** 单 sheet 异常 `session.begin_nested()` SAVEPOINT 回滚中途入库行 + **review M2** PriceRuleDraft `__post_init__` 空数组 raise + **review M4** `_match_identity` SUBSTRING_MIN_LEN=4 guard 防短串假阳。spec delta:MOD 5 Req(角色分类+identity / 报价表结构识别 / 报价数据回填 / 文档内容提取 textbox / 报价列映射修正)+ ADD 1 Req(identity_validator)。L1 **1115 绿**;L2 **281 绿**;前端 **114 绿**;真 LLM L2 golden(3 供应商 zip,~¥1)跑完 DB state 证明 6 项全生效(identity 3/3 正确 / B 家金额非 NULL / price_items 24 条 4× / 0 备注污染 / 0 纯数字 code);独立 reviewer 2 轮(pre-impl 3H5M4L + post-impl 3H4M4L)全吸收;**manual 凭证** `e2e/artifacts/parser-accuracy-fixes-2026-04-25/`(README 含 H2 证据限制说明 + golden_dump.json)|
| 先前 change | `config-llm-timeout-default` 归档完成。用户提供 3 个真实供应商 zip(投标文件模板2)做 E2E 验证,暴露 8 类问题,按 B 方案拆 3 change(CH-3 本/CH-1 parser-accuracy/CH-2 detect-template-exclusion)。本 change 为 CH-3(最小优先):`llm_call_timeout` 默认 60→300s;Windows lifespan 加 `sys.stdout/stderr.reconfigure(encoding='utf-8', errors='replace')` + AttributeError/ValueError 兜底,防中文日志 UnicodeEncodeError crash。L1 1022/1022 + 前端 114/114 + L2 281/281 全绿;`pipeline-error-handling` spec:MODIFIED 1 Req(默认 60→300) + ADDED 1 Req(Windows UTF-8 兜底);属 CLAUDE.md "孤立改配置" 例外(无 L3);零 UI / 零业务行为变化 |
| 最新 commit | `47f731f` 归档 change: fix-bug-triple-and-direction-high(3 bug + 9 对称性盲点 / 13 维 / 4 轮 reviewer) |
| 工作区 | **后端代码**:新建 `services/detect/template_cluster.py`(TemplateCluster dataclass + Adjustment TypedDict + AdjustedPCs/AdjustedOAs 双 dict + `_normalize_created_at` + `_build_cluster_key` + `_detect_template_cluster` union-find + `_apply_template_adjustments` 双 dict 不回写 ORM 含 DEF-OA OA 同步覆盖 + 4 维剔除 / text_sim 降权 ×0.5 + 铁证豁免)+ alembic `0012_add_template_cluster_fields.py`(2 字段);改 `models/analysis_report.py`(template_cluster_detected BOOLEAN + template_cluster_adjusted_scores JSONB.with_variant(JSON, sqlite));`schemas/report.py::ReportResponse`(+2 optional 字段);`services/detect/judge.py`(导入 template_cluster + DocumentMetadata + BidDocument;新 `_load_bidder_metadata` SQL helper join Bidder+BidDocument+DocumentMetadata where deleted_at IS NULL + file_role IN TEMPLATE_FILE_ROLES;`_compute_dims_and_iron` 扩 `*, adjusted_pcs / adjusted_oas` kwarg 优先读 adjusted dict;`judge_and_create_report` **6 步顺序改造**:step2 第一次 dims_iron(raw)→ step3 DEF-OA 写库 raw + `overall_analyses.append(oa)` 同步 local list → step4 cluster 识别 + 异常兜底 → step5 `_apply_template_adjustments` → step6 第二次 dims_iron(adjusted)+ formula_total/level 重算保留 weights/risk_levels 透传 + has_sufficient_evidence/run_l9 透传 adjusted dict + clamp + final_total/level + INSERT report 含 template_cluster_detected + adjusted_scores JSONB);`_run_l9` 扩 adjusted_pcs/adjusted_oas kwarg 透传 summarize;`services/detect/judge_llm.py`(`_has_sufficient_evidence` 扩 kwarg + iron 短路读 adjusted + 信号判定切 OA.score 分母;`_is_pc_ironclad` / `_is_oa_ironclad` 扩 adjusted dict kwarg;`summarize` 扩 kwarg + `_pc_score` nested 函数 inline 兜底替换 + `_is_*_ironclad` 调用全部传 adjusted dict);**测试 infra**:无 fixture/conftest 改动;**测试**:L1 新增 `test_template_cluster_detection.py`(14,union-find/normalizer/全角半角 case)/`test_template_adjustments.py`(13,4 维剔除 + 铁证豁免 + DEF-OA 覆盖 + ORM 不变断言 + 双 dict 命名空间隔离)/`test_has_sufficient_evidence_with_adjustments.py`(11,5 老路径 + 6 新路径 + DEF-OA list 长度断言)/`test_compute_dims_with_adjustments.py`(9,默认 None + adjusted 覆盖 + 6 步两次调用模拟 + C17 weights/risk_levels override 回归)/`test_summarize_with_adjustments.py`(7,helper kwarg + nested _pc_score inline 兜底);L2 新增 `test_template_cluster_exclusion.py`(5 case:全簇 17 条 adjustments + risk=low + DB raw 保留 / file_role 过滤 / 真围标 + 模板 → high text DEF-OA score=95 has_iron=true / metadata 全 NULL 回归 / indeterminate 专用 fixture);**L1 1161/1161 绿;L2 286/286 绿**;**前端 L1 114/114 绿**;**L3 手工凭证降级** `e2e/artifacts/detect-template-exclusion-2026-04-25/README.md`(0 UI 改动 + 0 前端 typescript 改动);**spec sync**:`detect-framework` ADD 2 Req(模板簇识别 + 维度剔除/降权与铁证抑制)+ MOD 1 Req(证据不足判定规则,扩 keyword-only `adjusted_pcs/adjusted_oas` 可选参数,任一非 None 时切 OA.score 分母 + iron 短路读 adjusted)|

---

## 2. 本次 session 关键决策(2026-04-25,`detect-template-exclusion` CH-2 propose+apply + **8 轮 reviewer**(从 over-spec 收手做减法)+ L1/L2/前端 L1 全绿 + L3 手工凭证 + 真 LLM golden 待用户授权)

### 上游触发
2026-04-24 用户 3 真实供应商 zip 暴露 P0-4(同 metadata 模板假阳)。CH-3 + CH-1 归档后进 CH-2 final round。

### propose 4 个产品决策

- **Q1 = A**(metadata 簇识别 + 维度剔除/降权);**Q2 = 删 D 兜底**(数学不可达 + A 已覆盖);**Q3 = A 保持** `template_cluster_detected = len(adjustments) > 0`(与 JSONB 同步);**Q4 = 做减法 M3**(spec 6 步顺序 + 行号下沉 design,只留语义 invariant 4 条)

### 8 轮 reviewer 收敛历程(从 over-spec 收手做减法)

| Round | HIGH 数 | 关键发现 |
|---|---|---|
| 1 | 6 | metadata_author iron 击穿 / metadata_time 双重计数 / D5 数学不可达 / primary_bid_document 虚构 / bool 语义重载 / agentTask 分母 |
| 2 | 3 | file_role "commercial" 不存在 / image_reuse 不写 iron / `_has_sufficient_evidence` 自相矛盾 |
| 3-1 | 3 | LLM summary bypass / compute_report 不被调用 / 单 dict id 命名空间冲突 |
| 3-2 | 1 | compute_report 签名 + 主 spec 2 处契约 |
| 4 | 2 | raw vs adjusted 双消费 + DEF-OA OA.id 物理时序 |
| 5 | 1 | spec L5 + L76 wording 自相矛盾 |
| 6 | 0 | 减法过关 |
| 7 | 1 | `_pc_score` 不是 module-level / `_compute_formula_total` weights 是位置参数 |
| 8 | 3 | `_pc_score` 真位置 + `fallback_conclusion` 不消费 PC/OA + weights/risk_levels 透传遗漏 + step6b 子步序顺序 |

**根因:作者凭印象写代码事实 → 反复出错。**收手判断在 round 5/6 后逐步明确,M3 减法是关键转折(spec 6 步顺序下沉到 design,留 4 条语义 invariant)。

### apply 现场决策(技术层,不问用户)

- **D1 author 归一化**复用 `nfkc_casefold_strip`(metadata_author agent 同 normalizer)
- **D2 cluster key**(author_norm, doc_created_at_utc_truncated_to_second);ヘッ集合相交非空 → union-find 等价类传递闭包
- **D3 双 dict 隔离 PK 命名空间**:`AdjustedPCs = dict[int, dict]` + `AdjustedOAs = dict[int, dict]`(避免 pc.id=1 oa.id=1 重叠错位)
- **D4 6 步顺序 + 第二次 `_compute_dims_and_iron`**:第一次 raw 给 DEF-OA 写库(D7 审计 raw 入库);第二次 adjusted 给 final_total/LLM(防 LLM clamp 拉回污染分);step6b 子步序锁:① dims_iron(adj) → ② formula_total(weights=) → ③ level(risk_levels=) → ④ has_sufficient_evidence(adj) → ⑤ run_l9 / indeterminate
- **D5 file_role 集合**:`{technical, construction, bid_letter, company_intro, authorization, pricing, unit_price}`(VALID_ROLES 对齐,排除 qualification 噪音 + other)
- **D6 helper kwarg 改造**:`_compute_dims_and_iron / _has_sufficient_evidence / summarize / _is_pc_ironclad / _is_oa_ironclad / _run_l9` 各加 `*, adjusted_pcs=None, adjusted_oas=None`;`compute_report` 签名/语义保持不变(主 spec L268/L2843 + 2 条 L1 signature_unchanged 测试不破);`_pc_score` 是 summarize nested function → inline 兜底替换(不必提到 module-level)
- **D7 DEF-OA OA.id 必须被 adjusted 覆盖**:`_apply_template_adjustments` 对受污染维度产 PC entry + DEF-OA OA entry,后者 score=`max(全集 adjusted-or-raw)`,has_iron_evidence=`any(全集 adjusted-or-raw iron)`
- **D8 alembic 0012**:加 2 字段(detected BOOLEAN NOT NULL DEFAULT FALSE / adjusted_scores JSONB nullable),JSONB 用 `JSONB.with_variant(JSON(), "sqlite")` 兼容 SQLite L1
- **D9 SQL `_load_bidder_metadata`**:join Bidder where `project_id=:pid AND deleted_at IS NULL` + BidDocument file_role IN TEMPLATE_FILE_ROLES + DocumentMetadata
- **D10 L3 手工凭证降级**:本 change 0 UI 改动 + 0 前端 typescript 改动,按 CLAUDE.md L113 "L3 flaky → 手工凭证" 条款,凭证 README 写明 L1/L2 全绿 + 0 UI diff + 跳过实跑

### 文档联动

- **`openspec/specs/detect-framework/spec.md` delta**:ADD 2 Req(模板簇识别 / 维度剔除/降权与铁证抑制)+ MOD 1 Req(证据不足判定规则,扩 keyword-only `adjusted_pcs / adjusted_oas` 可选参数 + OA.score 分母切换)
- **`docs/handoff.md`** 即本次更新
- **manual 凭证(L3)**:`e2e/artifacts/detect-template-exclusion-2026-04-25/README.md`
- **manual 凭证(真 LLM golden)**:待用户授权跑 tasks 6.1/6.2(3 供应商 zip ~¥1 + 5-10 分钟)

### 关键收益

- **3 家同模板 → low/indeterminate**(L2 5.1 严格断言 risk_level == "low",text DEF-OA adjusted=45.80 走 LLM mock 30 → low)
- **真围标 + 同模板 → high**(L2 5.3 验证 text iron 豁免保留 + section iron + error_consistency iron 独立信号链不被掩盖)
- **indeterminate 真实可达**(L2 5.4b 锁:全 SIGNAL adjusted=0 → 跳 LLM → indeterminate)
- **DB 审计**:DB 中 PC/OA score / is_ironclad 保留 raw,adjusted 仅在 `template_cluster_adjusted_scores` JSONB
- L1 1115→**1161 绿**(+46);L2 281→**286 绿**(+5);前端 L1 **114 绿**;C17 weights/risk_levels override 兼容回归通过

### 遗留到下次 / backlog

- **6.1/6.2 真 LLM golden 跑** [manual]:用户授权后跑 3 供应商 zip,期望 risk_level 从 high 降到 low/indeterminate(实际能否 in {low, indeterminate} 待 prod 数据验证)
- **archive 待跑**:跑完 golden 验证 OK 后开 `/openspec-archive-change detect-template-exclusion` + 自动 commit
- **R10b follow-up**:cluster 识别失败 + qualification 噪音 → 加 metric/logger.warning 监控钩子(本 change 不实施)
- **R11 follow-up**:created_at 秒级邻近碰撞 ±N 秒容忍配置项
- **R12 follow-up**:image_reuse 未来引入 has_iron_evidence 写入 → 决定是否纳入剔除白名单
- **R5 follow-up**:style 部分覆盖 N-gram 精细化(本 change 简化为 "全覆盖才剔除")

---

## 2.bak_parser-accuracy-fixes 上一 session 关键决策(2026-04-25,`parser-accuracy-fixes` CH-1 propose+apply+archive + 2 轮独立 reviewer)

### 上游触发
2026-04-24 CH-3 归档后,按 B 方案顺序进 CH-1(parser 精度 6 项)。

### propose 4 个产品决策(Q1-Q4 与用户对齐)
- **Q1 = C (P0-1)**:identity_info **LLM + 规则双保险**。prompt 加"投标方 ≠ 招标方"说明 + 落 DB 后规则扫 docx body 正则 `投标人(盖章)：XXX` 做 LLM-规则比对
- **Q2 = B (P0-3)**:`_parse_decimal` 扩 **"元/万元/万"** 后缀。中文大写"壹/贰"不扩(follow-up)
- **Q3 = B (P1-5)**:**BREAKING** `PriceParsingRule.column_mapping` → `sheets_config` 多 sheet 数组。alembic 自动转老数据;老 3 列 nullable 作 backward compat 缓冲(下个 change 删)
- **Q4 = B (P2-8)**:docx textbox 用 lxml `etree.XPath` 绕过 python-docx `BaseOxmlElement.xpath(namespaces=...)` 已废 kwarg,**不升级 python-docx**

### pre-impl reviewer 3 HIGH / 5 MEDIUM / 4 LOW → 全吸收
- **H1 正则 `[\n$]` 非 anchor** bug 改 `(?:\n|\s{2,}|$)`;三处同步(design + spec + tasks)
- **H2 column_mapping NOT NULL** 会卡新写入 → migration alter_column nullable + rule_coordinator 同步回写老 3 列做 schema buffer
- **H3 备注行只扫 code_col 漏真实布局** → 改扫 text 三字段(code/name/unit)任一 ≥100 字 + 其他全空 → skip
- M1-M5 全修(multi-sheet try/except / tasks 标签补全 / rule 非 confirmed 护栏 / PUT 混传 422 scenario / _llm_original L1 断言)

### apply 现场决策 + post-impl reviewer 又 3 HIGH / 4 MEDIUM / 4 LOW
- **H1(post-impl)matchident code/spec/test 三者矛盾**:spec 要"补齐不降级",代码和测试却降级。加 "fill" 决策分支 + spec 补 scenario "补齐场景不降级 role_confidence"
- **H2(post-impl)golden 未真验规则纠偏路径**:3 家 identity 全对实际是 LLM prompt 改善的功劳(`_llm_original` 0 命中),规则纠偏代码仅 L1 mock 覆盖 → README 补说明 + 标 follow-up 未来加 L2 mock LLM 反向 case
- **H3(post-impl)单 sheet 异常中途抛导致部分行残留**:原 try/except 外围无 savepoint,已 `session.add()` 的 N 行在外层 commit 时一并入库。改每 sheet `async with session.begin_nested()` SAVEPOINT 包裹 → 异常自动 rollback 该 sheet 全部行。加 L1 测试"坏表 row[0] OK + row[1] 抛"断言坏表 0 items
- **M1 残留备注污染**(3 行) → `_extract_row` 前置加"item_code 以'备注'开头 + 数值全空 → skip"
- **M2 PriceRuleDraft first_* properties returns None** → `__post_init__` raise + 类型改非 Optional
- **M4 子串假阳**("华建" in "江苏华建建设")→ `SUBSTRING_MIN_LEN=4` guard
- **L2 测试名误导** → rename `test_pure_digit_code_alone_kept_as_is`

### schema 改动 + alembic 策略
- `sheets_config` JSONB NOT NULL DEFAULT '[]' → UPDATE 老数据 → DROP DEFAULT → 老 3 列 ALTER NULLABLE
- downgrade 对称:sheets_config[0] 回写老列 → NOT NULL 恢复 → DROP sheets_config
- subprocess alembic 测试避开 pytest-asyncio event loop 嵌套(direct `command.upgrade` 会调 env.py 的 `asyncio.run()` 冲突)

### 文档联动
- **`openspec/specs/parser-pipeline/spec.md`** 5 MOD Req + 1 ADD Req 已 merge(archive 前 sync 脚本自动按 "### Requirement: <name>" 块切分替换)
- **`docs/handoff.md`** 即本次更新(section 2 重写,最近 5 条历史 shift)
- **manual 凭证** `e2e/artifacts/parser-accuracy-fixes-2026-04-25/`(golden_dump.json + README,含 H2 证据限制说明)

### 关键收益
- **identity_info 3/3 正确**(攀钢 / 浙江华建 / 江苏省华厦)vs CH-1 前的 2/3 错(A、C 被标招标方)
- **price_items 24 条** vs CH-1 前 6 条(4×;"监理人员报价单分析表"5 行真实明细首次入库)
- **B 家金额非 NULL**(486000元 → Decimal 486000.00)
- **0 备注污染**(3 行 "备注:" sentinel 全 skip)
- **0 纯数字序号 item_code** pollution
- schema 改动给未来多 sheet 价格表场景铺路;老 rule 自动转换,admin UI GET 仍读老字段无感
- L1 1115 / 前端 114 / L2 281 全绿;真 LLM golden 验证 6 项修复全生效

### 遗留到下次 / backlog(写进本 change 的 follow-up)
- **M3 textbox 测试 xml ns 脆弱**:用 python-docx 真生成 fixture 作 backstop(defer)
- **L1 subprocess alembic 并行**:pytest-xdist 多 worker 撞数据风险,加 serial mark
- **L3 num 列文本备注**:备注偶尔写数值列(如"见备注"),过 _parse_decimal=None 但绕过备注检测
- **H2 post-impl follow-up**:加 L2 mock LLM 反向 case 验证 identity 规则纠偏真触发
- **中文大写金额归一**(P0-3 选项 C):如"壹万贰仟元整",本 change 未做
- **CH-2 detect-template-exclusion**:下个 change,依赖本 change 提供干净 identity_info + 完整 price_items 做"同模板排除"判定

---

## 2.bak_config-llm-timeout-default 上一 session 关键决策(2026-04-24,`config-llm-timeout-default` propose+apply+archive + E2E 验证 3 供应商 zip 暴露 8 类问题)

### 上游触发
用户提供 3 个真实供应商 zip(`C:\Users\7way\xwechat_files\bennygray_019b\msg\file\2026-04\投标文件模板2\投标文件模板2\{供应商A,B,C}.zip`,工程监理项目),要求走完整 pipeline 验证。E2E 跑完 project 1728 发现:
1. 🔴 identity_info 把招标方"锂源(江苏)科技"识别成投标方(A、C 命中)
2. 🔴 3 家同 docx 模板(author=LP/created=2023-10-09 07:16)触发 structure=100 / text=91.59 / style=76.5 / metadata_author=62.5 分 → total=93 → risk=high 假阳性
3. 🔴 B 家"￥486000元"字符串 `_parse_decimal` 不剥"元" → up/tp 全 NULL
4. 🟡 LLM 默认 timeout 60s 对 ark-code-latest 太短(实测 35~132s);也是你之前看到的"xlsx 角色空白"根因
5. 🟡 fill_price 只扫 `rule.sheet_name="报价表"`(1 行真数据),漏"监理人员报价单分析表"(5 行真数据)
6. 🟡 备注长文本行(A 列长字符串 + B~G 全空)当 PriceItem 写入
7. 🟡 item_code 被映成"序号"列(A 列)
8. 🟢 `python-docx` textbox xpath namespaces 兼容问题 + Windows 控制台 GBK 中文日志 UnicodeEncodeError crash

### propose 2 个产品决策
- **Q0**:修复拆分策略 → 用户选 B(按领域拆 3 change):CH-1 parser-accuracy-fixes / CH-2 detect-template-exclusion / **CH-3 本 change(config/infra)**;顺序 CH-3 → CH-1 → CH-2
- **Q1**:CH-3 timeout 默认值 → 用户选 B(300s 保守)。A(180s)被否决(实测最坏 132s 仅 2.3x buffer 边缘 case 仍踩)

### apply 现场决策(技术层,不问用户)
- **D1 reconfigure 用 errors='replace'**:极端 Unicode 字符(罕见代理对)不崩 logger,降级成 `?`;比 errors='strict'(崩)或 errors='ignore'(丢字符)对诊断更友好
- **D2 放在 app logger setLevel 之前**:先把 stream 编码搞对再启子 logger;反序的话 setLevel 本身若日志中文就可能崩
- **D3 两个 stream 循环写**:stdout + stderr 对称处理,for 循环省代码
- **D4 L1 加 env_override 测试**:除"默认值=300"外,加一 case 测 `LLM_CALL_TIMEOUT=60` env 覆盖仍然生效 → pydantic-settings 契约没坏

### 文档联动
- **`openspec/specs/pipeline-error-handling/spec.md`** delta:MODIFIED Requirement "LLM 调用全局 timeout 安全上限"(默认 60→300,3 scenario 数字同步) + ADDED Requirement "Windows 控制台日志 UTF-8 兜底"(2 scenario)
- **`docs/handoff.md`** 即本次更新
- **manual 凭证**:`e2e/artifacts/config-llm-timeout-default-2026-04-24/`(backend_startup.log + health.json + README)

### 关键收益
- **CH-3 交付:LLM_CALL_TIMEOUT 默认 300s**:后续 CH-1 CH-2 的 L2 测试不再踩 60s timeout
- **Windows 日志不崩**:未来 E2E 验证、prod 日志可持续读
- **保留 CH-1 CH-2 的 backlog**:8 类问题中 1/3/5/6/7/8 进 CH-1(parser),2 进 CH-2(detect),4 本 change 解决

### 遗留到下次 / backlog(CH-1 范围)
- 🔴 **P0-1** identity_info prompt 区分投标方 vs 招标方
- 🔴 **P0-3** `_parse_decimal` 扩"元/万元/万"后缀归一
- 🟡 **P1-5** fill_price 多 sheet 扩展(识别"报价表"+"监理人员报价单分析表"等候选)
- 🟡 **P1-6** 备注长文本行识别(A 列长 text + B~G 全空 → skip)
- 🟡 **P1-7** item_code 为"序号"列时识别并空掉
- 🟢 **P2-8** `python-docx` textbox xpath namespaces 修复

### 遗留到下次 / backlog(CH-2 范围)
- 🔴 **P0-4** 招标方下发模板识别:同 author + 同 created_at 跨 bidder 阈值 → structure/text/style/metadata_author 维度降权或剔除(具体识别策略待 CH-2 propose 时讨论)

---

## 2.bak_fix-admin-users-page-flaky-test 上一 session 关键决策(2026-04-23,`fix-admin-users-page-flaky-test` propose+apply+archive)

### 上游触发
`test-infra-followup-wave2` 归档时遗留:前端全量跑 `npm test -- --run` 1 个 pre-existing flaky `AdminUsersPage 创建用户成功`(clean tree 同失败,isolated 跑绿),用户要求下一个 change 处理。

### propose 1 个产品决策(Q1=B 加 minimal spec)
- 小 fix 也走 openspec flow(CLAUDE.md 惯例);spec 加 1 ADDED Requirement "前端交互测试 timing 契约" 锁未来契约,不只修 bug

### apply 现场决策(技术层,不问用户)
- **D1 推翻**:design 预估 `userEvent.setup({ delay: null })` 单独足够,实测 3/3 稳定 fail(不是偶发!)—— 全量跑下 jsdom + antd + vitest workers 累积负载远比 keystroke delay 严重
- **D2 实测触发**:design 预估 fallback "<5% 偶发" 才加 timeout=15000,apply 期直接触发(100% 需要兜底);主备同出才稳定
- **spec 描述修正对齐实测**:从 "首选 delay:null,兜底 timeout" 改写为 "delay:null 或 test-level timeout≥15s 二选一或组合",契约意图保留但表述更精确(非更严格)
- **scope 锁死**:全项目 15+ `userEvent.setup()` 站点只改出问题的那 1 个(L100),其他 14 个无病例不动;spec 约束**未来**新测试,不追溯批改历史(memory 无病例不 preemptive 修复)

### 文档联动
- **`openspec/specs/pipeline-error-handling/spec.md`** +1 Requirement "前端交互测试 timing 契约" + 1 scenario
- **`docs/handoff.md`** 即本次更新

### 关键收益
- 前端 L1 **114/114 全绿连续 3 次稳定**(vs 前 113/114 稳定 fail)
- 未来前端 change 归档前 "npm test 全绿" 校验门从"1 fail 人工 pass" 回归到 "全绿自动 pass"
- spec 契约防未来新测试引入同型 flaky

### 遗留到下次 / backlog
- **Follow-up(低优)**:项目其他 14 个 `userEvent.setup()` 站点(AddBidderDialog / PriceConfigForm / PriceRulesPanel / AdminLLMPage / AdminRulesPage / ProjectCreatePage / AdminUsersPage 自身 L126)目前全绿无症状,无病例不主动修;若未来 suite 继续膨胀触发同型 flaky,单独处理
- **Follow-up(低优,pre-existing)**:9 个 spec validate 失败(handoff L58,scope 大,逐个看)

---

## 2.bak_test-infra-followup-wave2 上一 session 关键决策(2026-04-23,`test-infra-followup-wave2` propose+apply+archive)

### 上游触发
用户汇总前 3 次 change(harden-async-infra / agent-skipped-error-guard / llm-classifier-observability)的 3 条遗留(1 real bug + 2 latent),要求合 1 处理。handoff 扫出另 2 项同主题的 follow-up(uvicorn log 不级联 / text_sim degraded 前端覆盖空白),拒 1 项 scope 大的(9 个 spec validate 失败)、拒 1 项不同域的(前端 vitest flaky),最终 5 项 + handoff stale 清理合 1 change。

### propose 1 个产品决策(A/B/C bundle,对齐 A 合 1)+ 1 个新纳决策(Item 4 也纳入)
- 范围由 3 → 5 + 清理,scope 从 "合并前序 reviewer 遗留" 扩到 "合并前序 reviewer 遗留 + 本周发现的同主题 follow-up"
- Item 1 在 llm-classifier-observability apply 期 recon 已完全锁定根因(alembic fileConfig disable_existing_loggers=True),propose 阶段无遗留模糊;其他 4 项 design 级自决

### apply 现场决策(技术层,不问用户)
- **D1 Item 1**:alembic env.py 加 1 keyword arg(disable_existing_loggers=False),对 prod 严格更宽松
- **D2 Item 2 AST 级意外发现**:apply 期初版 AST 断言比老正则更严,flag 到 preflight try(broad except body 调 `_mark_skipped`,非 bug);精修契约为"仅 body 调 `_mark_failed` 的 broad except 强制 AgentSkippedError 前置",AST 真契约反而更准
- **D3 Item 3 mock 路径推翻**:apply 期实测 mock `_processes` 缺失直接破坏 pool 本体(stdlib `_adjust_process_count` 本身用 `_processes`),mock 拖垮 pool 启动而不是测 finally 块;切静态源码断言(try/except 结构 / fallback workers=[] / shutdown 调用)+ 实跑 happy path,更第一性、更稳
- **D4 Item 4 只 setLevel**:不搞 dictConfig / yaml,1 行 setLevel 让 `app.*` 子树默认 INFO;handler 级由 uvicorn/env 控制,prod warning 级不误爆 info
- **D5 Item 6 apply 期发现 DimensionRow 不消费 evidence_json**:frontend 层 DimensionRow 只读 `summaries[0]`,evidence_json 在 evidenceSummary 工具里消费;修正 Item 6 的测试语义为"degraded 非 skipped 的真实 shape(succeeded=1 + best_score>0)渲染回归网",贴近真实用户路径
- **pool._processes 反向验证案例**:apply 期跑 test_run_isolated_future_proof 3 次 mock 路径全 fail `'ProcessPoolExecutor' object has no attribute '_processes'`(stdlib 运行期自己需要),推翻 design 的 mock 方案;改静态断言 + happy path,同文件 4/4 绿

### 文档联动
- **`openspec/specs/pipeline-error-handling/spec.md`** 加 1 Requirement "测试基础设施鲁棒性契约" + 3 scenarios(alembic 不 disable app logger / `run_isolated` graceful degrade / engine except 顺序 AST 元测试)
- **`docs/handoff.md`** 即本次更新 + §2.bak_honest-detection-results 里 2 条 stale 项 strikethrough(agent 全仓 except guard 已被 agent-skipped-error-guard 落地 / text_sim _DEGRADED_SUMMARY 已被本 change Item 6 补强)
- **`backend/app/main.py`** lifespan 顶部 setLevel 注释引本 change

### 关键收益
- **L2 从 280/1fail 变 281/281 全绿**:Item 1 fix 顺带治好 pre-existing 稳定失败的 `test_xlsx_truncates_oversized_sheet`
- **engine except 顺序 AST 契约**:防未来重构破坏 harden-async-infra D2 核心(AgentSkippedError 必须在 Exception 之前),且精确到 `_mark_failed` 触发条件,不误报 preflight skipped 路径
- **run_isolated Py 3.14+ 兼容网**:stdlib 移除 `_processes` 时 graceful degrade,fallback 到纯 shutdown 路径
- **uvicorn log 级联修复**:未来 N3 类诊断 info 日志天然可见,不用再改 main.py
- **DimensionRow 前端降级文案回归网**:防未来改 DimensionRow 把 text_sim succeeded + summaries[0] 吞掉

### 遗留到下次 / backlog
- **Follow-up(下一个 change)**:`frontend/src/pages/admin/AdminUsersPage.test.tsx::创建用户成功` 全量跑 flaky(clean tree 上同失败,隔离跑绿,与本 change 无关)。用户已明确要求下一个 change 处理
- **Follow-up(低优,pre-existing)**:9 个 spec validate 失败(handoff L58,scope 大,逐个看),可后续单开

---

## 2.bak_llm-classifier-observability 上一 session 关键决策(2026-04-23,`llm-classifier-observability` explore+propose+apply+archive)

### 上游触发
`harden-async-infra` + `agent-skipped-error-guard` 归档后,唯一的 N3 backlog(LLM 大文档精度退化)进入 `/openspec-explore`。explore 阶段发现 harden-async-infra 补的 kind 日志只覆盖 3 决策路径中的 1 条(provider error),另 2 条(LLM 成功但自返 low / JSON 解析失败)完全隐身。无采样前任何 hardening 都是盲修。

### explore 阶段发现
- role_classifier 现有决策有 3 分支:`result.error != None`(有 kind 日志)/ `_parse_llm_json == None`(有 invalid JSON 日志但无 raw head)/ `LLM 成功返 low`(无日志);前 2 条可见,第 3 条需新加 info 日志
- 用户选 B 双采样(A+B × 2 轮,约 ¥0.2)以观察稳定性

### propose 2 个产品决策(Q1 对齐)
- **Q1 A**:最小 spec 改动。openspec validate 强制至少 1 delta,不能零 spec;折衷方案是写最小 ADDED Requirement(1 Req + 3 scenarios),只锁定"3 个日志点的存在性",不写 heuristic 细节 / 字段阈值等可变项
- 未来若 N3 数据指向 hardening 方向,在**下一个 change** 里再改 spec,本 change scope 锁死观测性

### apply 现场决策(技术层,不问用户)
- **D1 log level = info**:3 条新增日志用 logger.info(prod 默认 warning 级不显示,零噪声;诊断时主动调低)。既有 kind / invalid JSON warning 保留 warning 级不变
- **D2 只改 role_classifier 一个站点**:N3 只在 role_classifier 观察到;其他 5 LLM 调用点已有 kind 日志,不扩 scope
- **D3 mojibake heuristic**:纯启发式零依赖(25 个 cp850→GBK 乱码片段 markers,`any(m in name for m in markers)`),诊断用不触发业务控制流,误判无成本
- **D4 raw_text head 200 字符**:扩展既有 invalid JSON warning,追加 `raw_text_head=%r`,按字符(code point)截取 Unicode 安全
- **D5 采样脚本不复用 `run_detection.py`**:那是 detect 流水线,本 change 要的是 parse 流水线 + per-bidder snapshot,概念不同;强行抽 shared lib 反而 scope 爆炸
- **L1 fixture 复刻既有 `test_role_classifier_content_fallback.py` 风格**:独立 prefix `rc_obs_` 保证清理域不重叠(memory 习惯),不抽 shared lib

### Task 3.3 端到端 manual 执行(2026-04-23 session 内由 Claude 代跑)
- 起 dev postgres + alembic upgrade head + uvicorn(ark provider env 回退 admin-llm)
- `run_sampling.py` 2 轮 A+B,真 LLM(ark-code-latest),耗时约 2 分钟
- 产出 `round1.json` / `round2.json` / `comparison.json` / `backend.log`(311K)/ `sampling_run.log`
- **N3 原始症状不复现**:2 轮均 A/B `role_confidence_mix={high:3,low:0,none:0}`,完全一致
- 根因追溯:原 N3 是 H2a(`._` AppleDouble 文件污染 prompt,LLM 对混杂 8-10 条目的 prompt 整体降信心),`fix-mac-packed-zip-parsing` 把 `._` 文件在 zip 解压阶段过滤了,LLM 只看到 3 个真实 docx→信心恢复
- 2 就地发现:(a) uvicorn `--log-level info` 不级联 `app.*` logger,本次 3 条 info 未取到但 DB 状态 + warning 缺席推导 path 3 成功结论成立;(b) `run_sampling.py` v1 `file_role` 字段取错已就地修复(不影响 confidence 结论)

### spec 同步
- **`openspec/specs/parser-pipeline/spec.md`** 加 1 Requirement(role_classifier 诊断日志契约)+ 3 scenarios(LLM 成功路径记 input shape + output mix / LLM 失败路径仅记 kind 不记 output mix / JSON 解析失败路径 warning 带 raw_text_head)
- **`docs/handoff.md`** 即本次更新

### 遗留到下次 / backlog
- **N3 收官**:不单开 hardening change;观测性代码作为回归武器存档;若日后大文档 role 退化病例重现,直接跑 `run_sampling.py` 采样归因
- **Follow-up(低优)**:uvicorn 默认 log config 不级联 app logger 到 INFO。可在 `backend/app/main.py` lifespan 顶部加 `logging.getLogger("app").setLevel(logging.INFO)`,或用 `--log-config yaml`。单独改不值得开 change,并入下一个触碰 main.py 的 change
- **Follow-up(低优)**:9 个 spec 文件 openspec validate 失败(pre-existing,与本 change 无关),可后续单独处理

---

## 2.bak_harden-async-infra 上一 session 关键决策(2026-04-23,`harden-async-infra` propose+apply+archive)

### 上游触发
上一 change `honest-detection-results` 归档时遗留 4 条基础设施鲁棒性 follow-up(F1/N5/N6/N7),合并成本 change。N3 LLM 大文档精度先 `/openspec-explore` 不 propose。

### propose 2 个产品决策(Q1-Q2 与用户对齐)
- **Q1 A**:坏 docx 触发 subprocess 崩溃时,该投标人该维度标 `skipped` + 中文文案"解析崩溃/超时,已跳过"(语义一脉相承 F2 证据不足,不引入新 failed 状态)
- **Q2 A**:LLM 超时单次 skipped 不做重试(explore N3 需要 timeout 可观测信号;重试作为 N3 后续 if needed)

### propose 中发现并纠正 3 处原 design 错误假设(P1 recon 触发方案 B 重写)
- **N7 现状**:`OpenAICompatProvider.complete()` **已经**有 `asyncio.wait_for` + 不抛异常,原 design "基类加超时壳 + LLMTimeoutError 抛异常" 误读 — 改为 "6 调用点审计 + 归一降级" + 全局 cap;丢弃 `LLMTimeoutError` 新类
- **AgentRunResult 无 skip_reason 字段**:skipped 状态在 DB 的 `AgentTask.status + summary` — 改为新 `AgentSkippedError` 异常 + `summary` 中文文案,零 schema 变更
- **F1 范围 2→3 agent**:共享 `get_cpu_executor()` 还被 `structure_similarity` 使用,scope 补齐避免留死角

### apply 现场决策(技术层,不问用户)
- **D1 run_isolated 不用 `with` context manager**:reviewer H1 apply 期 L1 实测暴露 `ProcessPoolExecutor.__exit__` 默认 `wait=True` 在 hang worker 下跟着卡;改 `try/finally: pool.shutdown(wait=False, cancel_futures=True) + 遍历 pool._processes 主动 terminate(0.3s)+ kill` — L1 `test_hang_workers_do_not_accumulate` 5 次 hang 验证通过
- **D4 `_cap_timeout` 双路径 + 三防御**:env `get_llm_provider()` 与 DB `get_llm_provider_db()` 都过 cap;None/0/负数 → 默认 cap(防 admin 误配 NULL 或 0 让 `asyncio.wait_for(timeout=0)` 立即超时);cache key `max(1, int(_cap_timeout(raw)))` 防 0<raw<1 被 int 截断为 0(reviewer M2)
- **H2 style.py 必须写 OA stub 再 raise AgentSkippedError**:reviewer H2 指出 raise 直接逸出导致 OA 行缺失 → ReportPage 按 OA 枚举会丢 style 维度条目;修复:`except AgentSkippedError as skip_exc: write_overall_analysis_row(...stub...); raise` 保持与 pre-N7 降级路径行为一致
- **H1 testdb loud-fail 双层防御**:reviewer H1 指出 `pytest_configure` 基于 sys.argv 子串匹配,跑全量时不触发 → `tests/e2e/conftest.py::_testdb_schema` session fixture 改为 loud `pytest.exit(code=2)` 兜底,不 early-return
- **M1 error_consistency 预防性 except AgentSkippedError**:N3 explore 可能让 call_l5 改抛,提前加 `except AgentSkippedError: raise` 写 OA stub 再逸出,防未来 regression
- **spec scenario 3.6 修正**:apply 审 judge.py 发现原 spec 声称 "judge LLM 超时 → indeterminate" 与代码不符(代码是 `fallback_conclusion + formula_level` 保留公式信号)→ 修 spec 对齐代码(证据充分但 LLM 失败时保留信号更正确,不强降 indeterminate)
- **run_isolated 通过 `loop.run_in_executor(per_call_pool, ...)` 而非 `pool.submit`**:保留测试层 monkeypatch `loop.run_in_executor` 的兼容性 — 生产仍 per-task 隔离,测试层不需重写既有 fixture

### 文档联动
- **`openspec/specs/pipeline-error-handling/spec.md`** 加 5 Req / 12 scenario(ProcessPool per-task 隔离 + AgentSkippedError 契约 + LLM 调用降级白名单 + LLM 全局 timeout 上限 + skipped 原因文案规范)
- **`docs/handoff.md`** 即本次更新
- **`backend/README.md`** 加 L2 测试容器化跑法 3 行

### 独立 reviewer 2 轮 pre-impl + 2 轮 post-impl:CONDITIONAL GO → GO(最终)
- 第 1 轮 pre-impl:H1 pool `with` hang / H2 image_reuse 不调 LLM / H3 env 路径 cap 漏 / M1-M5 全修(design + spec + tasks 二次更新;新增 ProcessPool worker 主动 kill / spec scenario 移除 image_reuse / env 路径纳入 cap / None/0/负数防御)
- 第 2 轮 post-impl(agent spawn + 用户独立并行):H1 conftest loud-fail 门漏勺 / H2 style.py OA 缺失回归 / H3 OA 写入差异 / M1 error_consistency 前置 except / M2 cache key 0<raw<1 / M3 L1 _has_sufficient_evidence skipped / L2/L4 → 全修(tests/e2e/conftest.py loud-fail / style.py 写 OA stub / error_consistency 前置 except / factory.py max(1,int) / 新增 L1 agentskipped_error_filtered / Windows platform slack + +1 degraded 文案)

### 遗留到下次 / backlog
- **N3 LLM 大文档精度退化**(159MB 文档 LLM role confidence 全 low 场景):本 change 提供了精细化 kind 日志(6 调用点)+ timeout 可观测上限,为 `/openspec-explore N3` 准备好诊断工具。建议下一步 explore
- **`test_xlsx_truncates_oversized_sheet` caplog 未捕获 warning**:pre-existing 问题,clean testdb 下暴露(dev DB 下可能因测试顺序巧合通过)。与本 change 无关,标 follow-up
- ~~**agent 全仓防御 except AgentSkippedError: raise**~~ ✅ 已被 `agent-skipped-error-guard` 落地(6 agent 加 guard + AST 元测试强制);stale 记录移除
- ~~**text_similarity `_DEGRADED_SUMMARY` 文案覆盖**~~ ✅ 已被 `test-infra-followup-wave2` Item 6 补强(DimensionRow 新增 2 case 覆盖真实 shape)

---

## 2.bak_honest-detection-results 上一 session 关键决策(2026-04-23,`honest-detection-results` propose+apply+archive)

### 上游触发
上一 change `fix-mac-packed-zip-parsing` 归档时列出的 10 条 follow-up,其中 5 条(F2/F3/N2/N4/N8)合并成本 change "用户看得到的诚实性"。F1/N5/N6/N7 基础设施鲁棒性下次做;N3 LLM 大文档精度先 explore。

### propose 5 个产品决策(Q1-Q5 已与用户对齐)
- **Q1 B**:"非 skipped 的信号型 agent 全部 score=0 且无铁证" → 证据不足
- **Q2 C**:`risk_level` 新增 `indeterminate` 枚举值(不用标志位,一次到位类型系统强制覆盖)
- **Q3 L2+L3+L5**:身份信息缺失显示位置 = 投标人详情 Drawer 顶部 + 报告 error_consistency 维度 + Word 导出降级文案(不做列表页/对比页)
- **Q4 a**:ROLE_KEYWORDS 10 个强烈建议新词(价格标/开标一览表/资信标/资信/业绩/类似业绩/企业简介/施工进度/进度计划)
- **Q5 B**:归档行用 `antd Collapse ghost` 默认折叠,复用 DimensionDetailPage 已有 pattern

### apply 现场决策(技术层,不问用户)
- **D1 信号型 agent 白名单**:SIGNAL_AGENTS 只含 text/section/structure/image/style/error_consistency,剔除 metadata_* + price_consistency("0 == 没异常" 不算无信号)—— 缓解"干净项目被误判 indeterminate"
- **D1 铁证短路**:PC.is_ironclad / OA.has_iron_evidence 任一为 True → 证据充分 True(避免 `total_score=85 + risk_level=indeterminate` 自相矛盾)
- **D4 identity_info_status 放 ORM @property + from_attributes=True**:而不是 Pydantic computed_field(BidderSummary 没 identity_info 字段,computed_field 会 AttributeError)
- **D5 前端 TS 收紧路径**:`Record<RiskLevel, ...>` + 删 `| string` 逃生门 + 删运行期 `?? RISK_META.low` — 第 1 轮 reviewer 指出原"TS 强制覆盖"承诺是虚假保证,收紧后才真成立
- **D7 ROLE_KEYWORDS 同步约束降级**:SSOT=role_keywords.py;defaults 允许短子串(故意不强求值相等);弱一致性=defaults 每词 MUST 是 SSOT 某词的子串;prompts.py 不进机械测试(自然语言无可靠提取规则),靠 docstring 人工 review
- **D10 report_ready vs project.status 顺序**:INSERT AnalysisReport → UPDATE project.status 之间有 ~几十毫秒窗口,前端 MUST 以 report_ready 为权威拉取判据(spec scenario 明确)
- **I-3 补 DimensionRow 孤立组件测试**:第 3 轮 reviewer 指出 Task 5.7/6.4 降级 manual 后, `<Alert data-testid="dimension-identity-degraded">` 零自动化覆盖 — export DimensionRow + 4 case 孤立 render 测试

### 文档联动
- **`openspec/specs/detect-framework/spec.md`** 改:"综合研判骨架" 插 step4 + 加 scenario;"检测状态快照 API" 加 report_ready + 4 scenario
- **`openspec/specs/detect-framework/spec.md`** 加:"证据不足判定规则" / "AnalysisReport risk_level 新增 indeterminate" 两 Requirement
- **`openspec/specs/parser-pipeline/spec.md`** 改 "角色关键词兜底规则":加三副本同步约束 + 10 新词 scenario + authorization 条说明
- **`openspec/specs/report-view/spec.md`** 加 3 Req
- **`openspec/specs/report-export/spec.md`** 加 1 Req
- **`docs/handoff.md`** 即本次更新

### 3 轮独立 review 均 CONDITIONAL GO → GO(最终)
- 第 1 轮:TS 强制覆盖虚假保证 / BidderSummary 无 identity_info / 铁证 vs indeterminate 冲突 / 三副本 set 相等不可靠 — 全修
- 第 2 轮:BidderSummary computed_field AttributeError / _ALLOWED_RISK_LEVELS 漏改 / Word 模板 low/medium/high 回归 / report_ready vs project_status 顺序 — 全修
- 第 3 轮:useDetectProgress SSE risk_level 漏 indeterminate / report_ready 前端无消费点 / 2way sync 弱一致性缺失 / DimensionRow 零自动化 — 全修

### 遗留到下一 change(`harden-async-infra`)
- F1 ProcessPool per-task 进程隔离
- N5 testdb 容器化
- N6 `make_gbk_zip` fixture 重写
- N7 LLM provider `.complete()` 统一 `asyncio.wait_for`

N3 LLM 大文档精度先 `/openspec-explore` 再决定。11.3 Manual 观测建议:跑全量历史项目统计 indeterminate 占比,>5% 触发 design 复审。

---

## 2.bak_fix-mac-packed-zip-parsing 上一 session 关键决策(2026-04-23,`fix-mac-packed-zip-parsing` propose+apply+archive)

### 案例触发
- 真实 A/B zip(`e2e/artifacts/supplier-ab/supplier_A.zip` 166MB / `supplier_B.zip` 9.8MB,macOS Archive Utility 打包)暴露:parser 流水线**静默降级为无意义结果**(bid_documents.role 全 None、identity_info 全 null、检测报告"全零 + 低风险无围标"误导结论)
- 用户感知:"流程跑不同/卡住了" — 实则流水线跑完但结果全 0

### propose 阶段已敲定(产品/范围级决策)
- **A/B/C 选项分三层**:A 最小(只修 macOS 那批)、B 完整黑名单(+Windows/Office/VCS,**推荐选中**)、C 白名单严打(被否决:扩展名白名单过不掉 `~$x.docx` 这类恰好是 .docx 的临时文件)
- **区分"垃圾丢弃" vs "不支持但告知"**:打包垃圾 → 静默丢弃不产 bid_documents 行;非业务扩展名 → 保留 skipped 反馈用户
- **identity_info 不做规则兜底**:保持 spec 原意("避免精度差导致污染"),follow-up 由 UI/报告侧显示"识别信息缺失"文案

### apply 现场决策
- **保留 engine.py 既有 GBK 启发式 + 后置 UTF-8 校验**(而非整段删改):零回归路径,Windows GBK 包不受影响
- **`classify_by_keywords` 契约变更** None on miss(原返 "other"):便于上层两级兜底区分"命中 other" vs "未命中";同步更新唯一 production 调用点 + 2 个测试文件
- **fixture scope-safe 清理**:共享 dev DB 里有 project 226 的老数据,既有 `test_parser_llm_role_classifier.py` 的 `DELETE WHERE id>0` 会和 FK 冲突;改为按 `User.username` 前缀过滤只删本测试的 seed
- **端到端修 `_phase_extract_content`**(范围外但必要):真实 A/B 验收暴露 pipeline 把 .zip 归档行也扔给 `extract_content`,标成"未知文件类型 .zip" 覆盖我写入的 "已过滤 N 个" 审计文本;加一行 `file_type.in_([".docx",".xlsx"])` 过滤 + 回归测试
- **L2 fixture 手工构造 UTF-8-no-flag ZIP**:Python stdlib `zipfile` 对非 ASCII 文件名会强制置位 bit 11,无法原生模拟 macOS 无 flag 场景;手写本地文件头+中心目录+EOCD 精确控制 flag
- **manual 凭证用 JSON 代截图**:CLI 环境无 GUI,`verify.py` 调真 LLM 跑完整流程把 `bidders_before_detect / documents_A / documents_B / analysis_status / report` JSON 落盘到 `e2e/artifacts/supplier-ab/after-fix/`

### 文档联动
- **`openspec/specs/file-upload/spec.md`** 改 "压缩包安全解压" Requirement,+6 新 Scenario
- **`openspec/specs/parser-pipeline/spec.md`** 改 "LLM 角色分类与身份信息提取" + "角色关键词兜底规则" 两个 Requirement
- **`docs/handoff.md`** 即本次更新

### 发现但 **不在本次 change 范围** 的遗留问题(10 条)
参见 archive 目录 `openspec/changes/archive/2026-04-23-fix-mac-packed-zip-parsing/design.md` §5"Open Questions" 上下文。总览 + 优先级:
- **F2 高**:judge LLM 全零/全 skipped 时仍给"无围标"误导结论 — 应返"证据不足"
- **F1 中**:ProcessPool 崩溃兜底(per-task 进程隔离);A/B 案例靠垃圾过滤"绕过"但根因没修
- **F3 中**:identity_info NULL 时 UI/报告侧文案降级
- **N3 中**:大文档(如 161MB docx)下 LLM role_classifier 精度退化(A 全走兜底 low,B 全 high)— 需先开日志调查
- **N5 中**:共享 dev DB 污染导致 `pytest tests/e2e/` 全量跑不动 — testdb 容器化
- **N7 低-中**:LLM provider `.complete()` 没统一 `asyncio.wait_for`
- **N2 低-中**:`ROLE_KEYWORDS` 补 "价格标"/"资信标"(A 的"价格标/资信标"因此没命中 pricing/qualification)
- **N4 低**:analysis completion 与 report 生成时序不对齐(需加 `report_ready` 字段)
- **N6 低**:`make_gbk_zip` fixture 实际产出不是声称的东西(flag 被强制置位)— 重写
- **N8 低**:归档行(.zip)在 UI 的语义模糊 — 按 file_type 折叠

---

## 2.bak_admin-llm-config 上一 session 关键决策(2026-04-20,`admin-llm-config` propose+apply+archive)

### propose 阶段已敲定(5 产品级决策)

- **Q1 B dashscope + openai + custom**:白名单 3 种,custom = OpenAI 兼容端点
- **Q2 B 末 4 位保留**:`sk-****abc1`;短于 8 位固定 `sk-****` 占位
- **Q3 B 做测试连接按钮**:发 `"ping"` + max_tokens=1,最省 token
- **Q4 B 三层优先级**:DB > env > 代码默认;保持旧部署兼容
- **Q5 B 指纹哈希 cache + PUT 失效**:(provider, key, model, base, timeout) 作 key,PUT 后清空

### apply 现场决策

- **audit_log 暂不写 admin-llm 更新**:`AuditLog.project_id` 非空,系统级配置不挂项目;Follow-up 改 project_id nullable 或新建 SystemAuditLog
- **factory `get_llm_provider()` 保持同步签名 + env 路径**:11 个 Agent / judge / pipeline 现有调用零改动;新增 `get_llm_provider_db(session)` 异步路径供后续逐步切换
- **`@lru_cache` 换成 dict 指纹缓存**:上限 3,FIFO 淘汰,防病态输入撑爆
- **Tester `max_tokens=1` + timeout 强制 ≤10s**:防 UI 卡死
- **前端 api_key 空白不传**:占位符显示脱敏值,空白提交 → 后端保持旧值

### 文档联动

- **`openspec/specs/admin-llm/spec.md`** 新建:6 Req / 14 Scenario
- **`e2e/artifacts/admin-llm-2026-04-20/README.md`** L3 手工凭证
- **`docs/handoff.md`** 即本次更新

---

## 2.bak_C17 上一 session 关键决策(2026-04-16,C17 `admin-users` propose+apply)

- Q1 A 仅全局级 SystemConfig / Q2 A 覆盖写 + 恢复默认 / Q3 A admin 手动创建 / Q4 A §8 最小集
- L3 手工凭证:`e2e/artifacts/c17-2026-04-16/README.md`

---

## 2.bak_C15 上上一 session 关键决策(2026-04-16,C15 `report-export` propose+apply)

### propose 阶段已敲定(4 产品级决策)

- **Q1 C Word 模板两者结合**:内置默认 + 用户上传可覆盖 + 上传坏掉回退内置
- **Q2 D 复核粒度组合**:整报告级(必须)+ 维度级(可选)
- **Q3 A 独立 `audit_log` 表全字段**
- **Q4 D 异步 + 预览链接 + 三兜底**

### apply 阶段就地敲定(重要现场决策 B2)

- **design D4 改 B2**:原 design 假设复用 `async_tasks`,apply 发现侵入大;就地改独立 `export_jobs` 表(14 字段)

---

## 2.bak_C14 上一 session 关键决策(2026-04-16,C14 propose+apply+archive)

- Q1 B 预聚合结构化摘要 / Q2 A 公式兜底 / Q3 B 可升不可降+铁证 85 守护 / Q4 C 不做跨项目共现 / Q5 C 降级模板+前缀哨兵
- apply:AgentRunResult 字段名修正 / e2e autouse fixture / fallback 前缀约束 / summarize 铁证无条件入 top_k

---

## 2.bak_C13 上一 session 关键决策(2026-04-15,C13 propose+apply+archive)

- Q1 合并 / Q2 (A) L-5 铁证 / Q3 (C) MD5+pHash 双路 / Q4 (C) L-8 全 LLM / Q5 零新增依赖
- apply:不扩 AgentRunResult 改走 OA evidence 顶层 / DocumentText 行级 SQL / imagehash int64 cast

---

## 3. 待确认 / 阻塞

- 无硬阻塞,**M4 完成(3/3),全部 17 个 change 已归档**
- **Follow-up(C16)**:字符级 diff / price evidence 对齐 / 对比页面导出
- **Follow-up(C17)**:元数据白名单已通过 admin 规则配置可编辑（✅ 已解决）；按维度分 Tab 的完整配置 UI（第二期）
- **Follow-up(C15)**:用户模板上传 UI / PDF 导出 / 批量导出 / audit 过滤器 / 导出历史页
- **Follow-up(C14)**:跨项目历史共现 / DIMENSION_WEIGHTS 实战调参 / L-9 prompt N-shot 精调
- **Follow-up(持续)**:Docker kernel-lock 未解(C3~C17 L3 全延续手工凭证)
- **Follow-up(持续)**:生产部署前 env 覆盖全清单
- **Follow-up(产品决策搁置,2026-04-22)**:投标包内若报价单为 `.doc/.docx` 而非 `.xlsx`,当前链路**静默 skip**(无报错),导致 price_consistency 维度漏检
  - 现状代码位置:`run_pipeline.py:_find_pricing_xlsx` 硬过滤 `.xlsx` / `fill_price.py` 仅走 `extract_xlsx` / `price_consistency.py` preflight 找不到时 skip
  - 已评估两条路径并**搁置**:
    - 最小止血(1 天):改为显式 failed + UI 提示"报价单非 xlsx 格式,需人工"
    - 完整方案(6-8 天):抽象 tabular region + docx 表抽取 + LLM 兜底 C(详见此 session 讨论记录)
  - 触发重启条件:业务侧反馈 docx 报价单出现频率显著上升,或出现因此漏检的围标 case

---

## 4. 下次开工建议

**一句话交接**:
> **M4 完成,全部 17 个 change 已归档。** C15 报告导出 + C16 对比视图 + C17 用户管理/规则配置 = M4 可交付。系统具备完整的上传→解析→检测→报告→导出→对比→管理能力。下一步：M4 演示级交付凭证 + follow-up 规划（第二期 backlog 整理）。

**可直接粘贴给 AI 作为新会话起点**:
```
继续 documentcheck 项目。M4 已完成(3/3),C17 admin-users 已 archive + push。
全部 17 个 change（C1~C17）已归档,系统达到可交付状态。
下一步:
  1. M4 演示级交付凭证(execution-plan §4 要求:Word 报告示例 + 管理操作截图)
  2. follow-up backlog 整理(C14~C17 累积的 follow-up 项)
  3. 第二期规划(US-9.2 按维度分 Tab / US-10 LLM 配置 / 跨项目历史共现 等)
请先读 docs/handoff.md 和 docs/execution-plan.md §4~§6 确认现状。
也检查 memory 和 claude.md。
```

---

## 5. 最近变更历史(仅保留最近 5 条)

| 日期 | 变更 |
|---|---|
| 2026-04-25 | **`parser-accuracy-fixes` 归档(CH-1,B 方案 3-change 第 2 个)**:6 项 parser 层精度修复 + `PriceParsingRule` BREAKING schema(column_mapping → sheets_config 多 sheet);identity_validator LLM+规则双保险(fill / match / mismatch / unmatched 四决策,review H1 修);_parse_decimal 扩元/万元/万后缀归一;多 sheet 候选 + alembic 0011 兼容 migration(老 3 列 nullable + 同步回写作 backward compat);备注长文本三字段扫 + "备注:" sentinel 短词 skip;item_code 纯数字序号置空;docx textbox `lxml.etree.XPath` 预编译绕过 python-docx 已废 API;**H3 review 修**单 sheet 异常 `session.begin_nested()` SAVEPOINT 回滚中途入库行。L1 1115 + L2 281 + 前端 114 全绿;真 LLM L2 golden(3 供应商 zip ~¥1)证明 identity 3/3 正确 + 24 price_items(4×)+ 0 污染;独立 reviewer 2 轮 10H/9M/8L 全吸收;spec 5 MOD + 1 ADD Req |
| 2026-04-24 | **`config-llm-timeout-default` 归档(CH-3,B 方案 3-change 拆分第 1 个)**:用户提供 3 供应商 zip 做 E2E 验证暴露 8 类问题(identity 误判招标方 / 同模板假阳性 / B 家金额 NULL / LLM 60s 超时 / 漏扫 sheet / 备注行污染 / item_code 错映 / Windows log crash);本 change 最小优先:`llm_call_timeout` 默认 60→300s(ark-code-latest 实测 35~132s)+ lifespan `sys.stdout/stderr.reconfigure(utf-8, errors='replace')` + 2 try/except 兜底;L1 1022/1022 + 前端 114/114 + L2 281/281 全绿;`pipeline-error-handling` spec:MOD 1 Req + ADD 1 Req(Windows UTF-8 契约 2 scenario);CLAUDE.md "配置例外"不跑 L3;零业务/UI 变化;CH-1 CH-2 backlog 已记录 |
| 2026-04-23 | **`fix-admin-users-page-flaky-test` 归档**:前端 `AdminUsersPage 创建用户成功` 全量跑 flaky 修复。`userEvent.setup({ delay: null })` 移除 keystroke microtask + test-level `timeout=15000ms` 兜底(apply 期实测 D1 单独 3/3 fail,主备同出才稳定)。前端 L1 **114/114** 连续 3 次稳定;`pipeline-error-handling` +1 Requirement "前端交互测试 timing 契约";scope 锁死只修 1 站点不批改其他 14+ `userEvent.setup()` 历史站点 |
| 2026-04-23 | **`llm-classifier-observability` 归档**:N3 LLM 大文档精度退化收官。`role_classifier.py` 加 3 条 info 诊断日志(input shape / output confidence mix / invalid JSON raw_text_head)+ `_looks_mojibake` heuristic + 1 ADDED Requirement 进 parser-pipeline spec;L1 新增 11 case 全绿,测试总 1011 绿;Task 3.3 manual 真 LLM 双采样(ark provider,~¥0.2)证明 N3 原始症状不再复现(A/B 2 轮均 high=3 low=0 完全一致),根因 H2a 已被 `fix-mac-packed-zip-parsing` 顺带修掉;观测性代码作未来回归武器存档 |
| 2026-04-23 | **`harden-async-infra` 归档**:F1 ProcessPool per-task 隔离(3 agent × `run_isolated` + finally terminate/kill)+ N7 LLM 6 调用点降级归一 + `factory._cap_timeout` 两路径 + None/0/负数防御 + cache key `max(1, int())`  + N5 testdb 容器化(`docker-compose.test.yml` + conftest 双层 loud-fail)+ N6 `make_gbk_zip` 手写字节重写(old stdlib `zipfile` bit 11 强制置位致 fix-mac-packed-zip-parsing 自动回归失效)+ 集中 `errors.py` 7 常量 + `AgentSkippedError` + style/error_consistency 写 OA stub 保前端维度完整;L1 988 + L2 274/275 + 前端 12/12 全绿;合并 1268/1269 in 3:17;2 轮独立 reviewer + 2 轮 post-impl 全吸收(H1 pool hang 实质修 / H2 OA stub / M2 cache key 0 塌陷 等) |
