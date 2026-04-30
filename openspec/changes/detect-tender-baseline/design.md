## Context

- **当前架构**:`detect-template-exclusion`(2026-04-25 归档) 的 `template_cluster.py` 用元数据指纹 (author + doc_created_at) 识别模板簇,对 5 维 (structure_similarity / metadata_author / metadata_time / style / text_similarity) 做剔除/降权;其余 7 维不接入。`text-sim-exact-match-bypass`(2026-04-29 归档) 在 `text_sim_impl/tfidf.py` 加段级 sha1 hash 旁路,让字符 100% 相同段直接 sim=1.0,但 ≥50 字 exact_match 段直接顶 ironclad —— 模板段一律误报。
- **实测数据**(本次客户提供模板 zip):资信标 docx 136 非空段 / 34 段 ≥50 字;价格标 docx 27 段 / 4 段 ≥50 字;技术标 docx 13 段 / 0 段 ≥50 字;BOQ xlsx 3 sheet 24 行,列字段 = `(项目名 + 描述 + 单位 + 工程量)` + 应标方填的单价/合价。
- **复用现有架构**:`PairComparison.version` 自然递增重跑(`analysis.py:140`)、`template_cluster._apply_template_adjustments` adjustments 管道 (`AdjustedPCs/AdjustedOAs` 双 dict 不回写 ORM)、上传/解析管道 (`bidders.py` 的 `_persist_archive` + `trigger_extract`)、judge 6 步顺序流程、Ant Design + `tokens.ts` 色板。
- **proposal** 已确认产品语义(三级降级、可选、版本化、共识 N=3、BOQ key 不含价、用户立场:文本单维度可独自铁证)。本 design 解决"如何实施"。

## Goals / Non-Goals

**Goals:**

- 三级降级 (L1 tender hash / L2 共识 ≥3 distinct bidders / L3 ≤2 警示) 完整覆盖三种场景;**L3 仅加 `warnings`,不动 ironclad**(用户产品立场:基线缺失 ≠ 信号无效;text/section 单维度仍可独自顶铁证)
- 4 高优 detector (text/section/price_consistency/price_anomaly) 同步接入,evidence_extras 加 `baseline_source` 追溯
- **BOQ 项级 baseline 仅 L1 tender 路径,不走 L2 共识**(应标方填同一份工程量清单是合法行为)
- 复用 `template_cluster.py` 现有 adjustments **执行器**(`_apply_template_adjustments`),由 baseline_resolver 当**生产者**直接产 `Adjustment` list 喂入,template_cluster 不内嵌 baseline 业务逻辑
- 前端 `VITE_TENDER_BASELINE_ENABLED` feature flag 灰度兜底
- 零数据迁移,向前兼容(老 `PairComparison.version` 只读保留)
- alembic 单调向前(不需 downgrade 即可回滚)

**Non-Goals:**

- 不重写 detector 内部算法(`text_sim_impl` / `section_sim_impl` / `price_impl` 内部不动)
- 不引入 ngram / MinHash / shingle (留 v2,见 `docs/handoff.md` §1.1)
- 不引入外部模板语料库(留 v2 if 必要)
- 不接入 `image_reuse` / `error_consistency`(留 follow-up change)
- 不解析 PDF 扫描件招标文件(本次仅 docx + xlsx 干净路径)
- 不动 `PairComparison` 表 schema(只新建 `TenderDocument` + 加字段)
- 不引入 runtime feature flag (LaunchDarkly 等),只 build-time 环境变量

## Decisions

### D1: TenderDocument 独立表(不扩 BidDocument)

**选**:新建 `models/tender_document.py` `TenderDocument(id, project_id FK, file_name, file_path, md5, parse_status, created_at, deleted_at)`

**备选 A 不选**:扩 `BidDocument` 加 `doc_kind ∈ {bid, tender}` —— 污染 18 个消费方(`schemas/bid_document.py` / `routes/bidders.py` / `routes/compare.py` / `routes/projects.py` / parser pipeline / template_cluster file_role 过滤 / 前端 `RoleDropdown` / `FileTree` / 追加上传 unique key 等);BidDocument 已 FK 到 bidder,tender 属 project 级,语义错位。

**理由**:A1+A4 调研一致结论;独立表 hash 索引管理也独立。

### D2: segment_hash = SHA256 + 复用 `_normalize` 归一化

**选**:`DocumentText` 加 `segment_hash VARCHAR(64) NULL` 字段;归一化复用 `text_sim_impl.tfidf._normalize`(NFKC + `\s+→' '` + strip)保证与 `text-sim-exact-match-bypass` 口径统一;算法 sha256 hexdigest。

**备选**:sha1 / blake2b / xxhash —— sha1 已 deprecated for new code,blake2b 长度问题(56 位),xxhash 引新依赖;sha256 标准库 + 业内认可 + < 1ms / 段。

**实施**:`run_pipeline.py` 切段后批量计算入库;现有归档项目段 NULL,新检测时 lazy fill 或留 NULL 不影响(baseline_resolver 兜底跳过 NULL)。

### D3: `baseline_resolver.py` 独立模块边界

**选**:新建 `services/detect/baseline_resolver.py`,职责:
- 加载 tender hashes(按 dimension 分粒度:段级 set / 章节级 set / BOQ 项级 set)
- 计算共识(`segment_hash → set[bidder_id]`,size ≥3 触发)
- 判定 baseline_source ∈ `{tender, consensus, metadata_cluster, none}`,优先级 `tender > consensus > metadata_cluster > none`
- 接口:`resolve_baseline(session, project_id, dimension, raw_pairs) -> BaselineResolution(excluded_pair_ids, baseline_source, warnings)`

**整合点**:`judge.py` step5 之前调用 `resolve_baseline()` 拿 `BaselineResolution`,喂给 `template_cluster._apply_template_adjustments` 作为新增入参,管道内分发到 `tender_match` / `consensus_match` 两个新 reason 分支。

**备选**:深扩 `template_cluster.py` 内部 —— 单文件复杂度上升、回归风险大,新建模块边界更清晰。

### D4: 共识计数口径 = distinct bidder set 规模

**选**:在 baseline_resolver 内构建 `segment_hash → set[bidder_id]`,size ≥3 触发(忽略 hash 在多少 PC pair 中出现的次数)。

**备选**:按 PC pair 计数 —— 一个段在 (A,B), (A,C), (B,C) 3 对 PC 命中 = 3 计数 ≠ 3 家。语义偏差。

**理由**:业务语义"3 家以上同源" = bidder 数量,不是段对数量。

### D5: BOQ hash key 不含价格 + 仅 L1 tender 路径

**选**:`sha256(nfkc_strip(项目名) + '|' + nfkc_strip(描述) + '|' + nfkc_strip(单位) + '|' + decimal_normalize(工程量))`

**备选**:整行 hash(含单价/合价)—— 应标方填的单价/合价不同则 hash 完全不命中,等于无基线。

**理由**:工程量是招标方下发参数,单价/合价是应标方差异化输入;包含价格违反"模板字段 vs 应标方字段"的语义边界。

**关键约束(R5 reviewer 揭露 H3)**:**BOQ 项级 baseline 仅支持 L1 tender 路径,L2 共识不适用**。原因:招标方下发同一份 BOQ 给 4 家应标方,4 家填的"项目名+描述+单位+工程量"必然完全相同(招标方约束),hash 在 ≥3 家命中是合法行为不是模板冒充铁证。L2 共识规则若适用 BOQ → 把 4 家 BOQ 全部干掉变零分,price_consistency / price_anomaly 维度归零。

**实施**:`baseline_resolver.resolve_baseline()` 入参 `dimension` 区分 `text_similarity` / `section_similarity` / `price_consistency` / `price_anomaly`;BOQ 类维度只走 tender 路径,共识路径直接返回空 excluded_pair_ids。

**Open Question Q1**:工程量精度归一化("1.0" vs "1" vs "1.000")—— 用 `Decimal(str).normalize()` 去尾随零,L2 实测调优。

### D6: 多份 BOQ xlsx 不区分文件归属

**选**:同一 project_id 下所有 tender xlsx 行 hash 合进项目级一个 set。

**备选**:按文件名严格匹配(应标方"报价表.xlsx"对应 tender"报价表.xlsx")—— 应标方常改文件名,匹配失败率高。

**理由**:tender 是基线源,基线源越宽误差越向"模板"倾斜(不会冤判模板成串标);应标方写的真单价仍不会命中(hash 不含价格)。

### D7: hash 索引存储位置(分粒度)

| 粒度 | 存储 | 计算时机 |
|---|---|---|
| 段级 (text_similarity) | `DocumentText.segment_hash` 字段 | parser 切段后 batch 写入 |
| 章节级 (section_similarity) | runtime 计算 | detector run 时即时聚合 |
| BOQ 项级 (price_consistency) | `PriceItem.boq_baseline_hash` 字段 | parser 价格回填后 batch 写入 |
| BOQ 项 + bidder 级 (price_anomaly) | runtime 计算 | detector run 时聚合 |
| 图片级 (image_reuse) | `DocumentImage.md5` 已存在 | **本次不动**,留 follow-up |

**备选**:单独 `SegmentHash` 表 / Redis —— 增 schema/部署依赖,与现有架构不一致。

### D8: 重跑触发 = 复用 `analysis.py:140 max(AgentTask.version)+1`

**选**:补传 tender 后前端弹 dialog "立即重新检测?是/否"
- 用户点"是" → POST `/api/projects/{pid}/analysis`(现有端点) → 自动 `max(AgentTask.version)+1` → SSE 推进度
- 用户点"否" → 老 version 保留只读;UI 在该 version 头部加 stale Badge"v_n 数据未含本次招标文件,可能存在误报"

**备选**:补传后自动触发重跑 —— 用户失控感;LLM 可能消耗成本而用户没准备好。

**注**:`AgentTask.version` 与 `PairComparison.version` 共享同一 version 体系(同一次检测产出的所有 AgentTask + PairComparison 共用同一 version 值)。proposal/spec 文中提到的"PairComparison.version 自然递增" / "PairComparison.version+1" 语义正确,但**实际 SQL 写入端是 AgentTask 表**。本 change 文档为消费方视角统称为"version 体系",两者强一致;后续读者如需溯源写入点 → `analysis.py:140 max(AgentTask.version)+1`。

### D9: evidence_extras.baseline_source 字段

**Schema 扩展**(向后兼容):
- `PairComparison.evidence_json` 加 `baseline_source ∈ {"tender", "consensus", "metadata_cluster", "none"}` 顶级字段
- `template_cluster.Adjustment.reason` 枚举扩 `"tender_match"` / `"consensus_match"`
- 老 evidence(本字段缺失)前端 fallback 渲染 "none"
- 优先级:tender > consensus > metadata_cluster > none(同段多 source 命中取最强)

### D10: 前端 feature flag = `VITE_TENDER_BASELINE_ENABLED`

**选**:Vite build-time 环境变量,默认 `false`。
- 关闭时:项目页/报告页"招标文件"区块隐藏 / 模板段灰底渲染禁用 / 启动检测预检查 dialog 跳过 / 重跑 dialog 跳过 / 基线状态 Badge 隐藏
- **后端不受 flag 影响** —— 始终计算 baseline_source 并写 evidence;flag 只控制 UI 展现

**备选**:runtime feature flag (LaunchDarkly 等)—— 超出现阶段需求,过度设计。

**解禁条件**:客户验收 OK,改 `frontend/.env` `VITE_TENDER_BASELINE_ENABLED=true` 重新构建部署。

### D11: L3 凭证最小集 → 完整集分级

- **最小集**:text_similarity 单 detector 接入完成时(D12 步骤 ③ 完成),用客户演示 zip 跑一次,确认主路径 OK,**不进 4 detector 全部接入再跑**(避免方向错跑全套白烧 LLM)
- **完整集**:4 detector 全接入 + 前端 UI 全就绪后(D12 步骤 ⑦ 完成),客户演示 zip + 本次模板 zip 双套
- **截图凭证**:tender 上传卡 / 启动检测预检查 dialog / 报告页基线 Badge / 双栏对比模板段灰底 / 重跑 dialog,合计 5 张
- **真 LLM 调用**:双套 zip 各跑 1 次,预估 ¥3-5 / 15-20 分钟

### D12: apply 分批节奏(强制)

| 步 | 范围 | 验证门 |
|---|---|---|
| ① | alembic 0014/0015/0016 + `TenderDocument` 模型 + tender 路由 + parser segment_hash 索引 + LLM mock fixture | L1+L2 全绿 |
| ② | `baseline_resolver.py` 单测 + `template_cluster.py` 新 reason 分支 + `judge.py` step5 注入点 | L1+L2 全绿 |
| ③ | text_similarity 接入 + L3 最小集(客户演示 zip) | L1+L2+L3 最小集全绿 |
| ④ | section_similarity 接入 | L1+L2 全绿 |
| ⑤ | price_consistency 接入 | L1+L2 全绿 |
| ⑥ | price_anomaly 接入 | L1+L2 全绿 |
| ⑦ | 前端基线 UI + feature flag(默认关) + 类型 + API 客户端 | 前端 L1 全绿 |
| ⑧ | L3 完整集(双 zip 复跑) + 凭证截图归档 | L3 凭证齐 |

每步阻塞下一步;任一失败立即修。

### D13: tender 解析路径独立(R2 reviewer 揭露 H2)

**问题**:`extract/engine.py trigger_extract(bidder_id: int, password=None)` 现有签名按 bidder 写死,内部 `extract_archive(bidder_id)` 全部依赖 BidDocument 表。tender 没 bidder,**无法直接复用**。

**选**:扩 `trigger_extract` 签名为 `trigger_extract(*, bidder_id=None, tender_id=None, password=None)`,二选一参数 + 内部分发到 `_extract_bidder_archive(bidder_id)` 或 `_extract_tender_archive(tender_id)` 私有 helper。共享 zip 安全解压逻辑(zip bomb 防护 / 路径穿越 / 密码重试)。

**备选**:完全新建 `extract/tender_engine.py` —— 代码重复;两份解压安全逻辑同步维护成本高。

**理由**:tender 与 bidder 的解压安全约束完全相同,共享 helper 合理。新增 1 个分发分支比新建文件低风险。

`_persist_archive` 同理:扩 `routes/bidders.py:93 _persist_archive` 提到 `services/uploads.py` 给 tender / bidder 两路由共用;或在 `routes/tender.py` 新写 `_persist_tender_archive` helper(取舍由 apply 阶段实测决定)。

### D15: aggregate_bidder_totals 加 excluded_price_item_ids 参数(R4 第二轮 NH2 揭露)

**问题**:`anomaly_impl/extractor.py:aggregate_bidder_totals` SQL 端 `SUM(PriceItem.total_price)` GROUP BY bidder,返回值仅 `(bidder_id, bidder_name, total_price)`,**不带 PriceItem 行级信息**。tasks 6.1 原"在 price_anomaly.py:run() 外部过滤 PriceItem"逻辑不通(SUM 之前要过滤,但 SUM 在 SQL 端做)。同时 `aggregate_bidder_totals` 被 `price_anomaly` / `price_overshoot` / `price_total_match` 三个 agent 共用,**直接改 SQL 会污染另两个不在本次范围的 detector**。

**选**:扩 `aggregate_bidder_totals` 签名加 keyword-only `excluded_price_item_ids: set[int] | None = None` 参数:
- 默认 `None` 时 SQL WHERE 子句不加额外过滤,**三个共用 agent 行为完全不变**(向后兼容)
- 非 None 时 SQL WHERE 子句加 `AND PriceItem.id NOT IN :excluded_price_item_ids` 过滤
- 仅 `price_anomaly.run()` 在调用前先 query 出 tender BOQ hash 命中的 `PriceItem.id` 集合,作为该参数传入

**备选 A 不选**:price_anomaly.run() 自己跑独立 SUM 逻辑,绕开 `aggregate_bidder_totals` —— 重复 SUM 逻辑、绕开 sheet_role / max_bidders / NULL filter,等于 fork extractor。

**备选 B 不选**:动 SQL 改 GROUP BY HAVING —— 影响所有共用 agent,需要全维度回归。

**理由**:① 向后兼容(默认 None 三个 agent 行为不变) ② 改动量最小(单函数加 1 个 keyword-only 参数 + 1 个 WHERE 条件) ③ 复用现有 SUM 逻辑保留 sheet_role / max_bidders 等约束 ④ L1 单测可单独覆盖"默认 None vs 传 set"两条路径

**实施分工**:
- `aggregate_bidder_totals` 函数本身改造在 tasks 6.1
- `price_anomaly.run()` 调用前的 PriceItem.id 集合查询(`SELECT id FROM price_items WHERE project_id=:pid AND boq_baseline_hash IN :tender_hashes`)归 baseline_resolver 模块处理(避免 detector 直接跑 SQL 拼装 baseline)

### D14: baseline_resolver 生产者 + template_cluster 纯执行器(R1+R2 reviewer 揭露 H3 + M1.10)

**问题**:`template_cluster._apply_template_adjustments` 原设计是"metadata 簇专属",签名 `(pair_comparisons, overall_analyses, clusters)`,内部依赖 `cluster.bidder_ids` 做 pair 包含判定。直接塞入 tender_match/consensus_match 分支 → 函数承担 3 reason 5 分支 + 段对级 vs bidder 级语义混合,违反 detect-template-exclusion 第 5 轮 reviewer "做减法"原则。

**选**:**baseline_resolver 当生产者** + **template_cluster 当纯执行器**:
- baseline_resolver 新增 `produce_baseline_adjustments(session, project_id, dimension, raw_pairs) -> list[Adjustment]`,直接产 `Adjustment` list(reason ∈ {`tender_match`, `consensus_match`})
- `template_cluster._apply_template_adjustments` 签名扩 `extra_adjustments: list[Adjustment] = []` 参数,内部把 metadata_cluster 自产的 + 外部喂入的 baseline adjustments **合并**(同 PC.id 取最强 source 优先)
- template_cluster **不新增** if/elif baseline 业务分支;reason 枚举仅由调用方决定

**实施分工**:
- baseline_resolver 知道:tender hashes / 共识算法 / file_role 分组 / 优先级合并(tender > consensus > metadata_cluster > none)
- template_cluster 知道:Adjustment 怎么应用到 PC.score / is_ironclad / DEF-OA 重聚合(本来就知道)
- judge.py step5 顺序:① 调 `_detect_template_cluster()` 拿 metadata 簇 → ② 调 `baseline_resolver.produce_baseline_adjustments()` 拿 tender/consensus adjustments → ③ 调 `_apply_template_adjustments(pcs, oas, clusters, extra_adjustments=baseline_adjustments)` 一次性合并应用

**tender_match / consensus_match score 语义**(R2 H3 关键澄清):
- `score = 0.0`(与 metadata_cluster 一致,纯模板段不参与 detector 总分)
- `is_ironclad = False`(从触发集剔除)
- `evidence_extras.template_cluster_excluded = True`(复用现有标记) + `baseline_source ∈ {tender, consensus}` 区分来源

**L3 警示模式语义澄清(R1 H1 修正)**:L3 ≤2 投标方时 baseline_resolver MUST NOT 产 Adjustment(excluded_pair_ids 为空集);**仅返回 warnings='baseline_unavailable_low_bidder_count'**,由 judge.py 写入 evidence_extras.warnings;detector ironclad 触发逻辑保留原行为(text/section 单维度可独自顶铁证)。

**理由**:reviewer #1 M10 + reviewer #2 H3 同方向 finding;职责单一;后续 v2 / follow-up change 加新 baseline 信号源(如外部模板语料库)只动 baseline_resolver 不动 template_cluster。

## Risks / Trade-offs

| Risk | Mitigation |
|---|---|
| 4 detector 同时接入引发回归 —— 某个接入错破坏现有铁证识别 | D12 严格分批节奏,每步 L1+L2 全绿才下一步 |
| 模板真实复杂度 > 用户给的 4 文件样本 | 本次仅 docx + xlsx 干净路径;PDF 扫描件 / 答疑文件 / 招标文件正文留 follow-up;Non-Goal 显式声明 |
| 前端组件影响所有项目页面(不只新跑的) | feature flag `VITE_TENDER_BASELINE_ENABLED` 默认 false 灰度兜底 |
| 历史 v1~v5 数据被破坏 | 复用 `PairComparison.version` 机制,老数据零迁移、只读保留;URL 仍可访问历史 |
| reviewer 多轮发现根本性 design 缺陷 → 推倒重来 | 强制 propose 双 reviewer 收敛全部 HIGH 才进 apply |
| L3 真 LLM 跑成本 + 时长 | 最小集(单 detector) → 完整集(4 detector)分级跑;最小集发现方向错可早停 |
| BOQ hash 不含价格,但应标方填工程量微改(如 1.5 vs 1) | baseline 失效时退回 metadata_cluster + consensus 兜底;v2 评估补 fuzzy match |
| 共识 ≥3 在项目恰好 3 家时退化为"全部相同 = 模板" | 设计本意如此,proposal 已声明;UI 警示提示用户 |
| segment_hash 段长度归一化后过短(如"投标人:")会大量假命中 | baseline_resolver 加 `MIN_HASH_LENGTH = 5` 守门,与 text_sim_impl 现有阈值参数化对齐 |
| evidence_json schema 扩 baseline_source 老 evidence 不含 | 前端容错 fallback 默认 "none";后端不补迁移 SQL |
| feature flag 关闭时后端仍计算 baseline_source | 设计如此(前后端解耦);flag 解禁后历史 evidence 立即可视,无需重跑 |
| metadata_cluster + tender_match 同时命中(模板簇 + 招标文件)优先级处理 | D9 优先级取最强 source;adjustments 不双计(每段对 PC 只产 1 条 adjustment) |

## Migration Plan

**部署流程(单步)**:

1. 合并 PR + 后端部署(含 `alembic upgrade head` 自动跑 0014/0015/0016)
2. 老 `PairComparison.version` 数据保留只读
3. 前端构建带 `VITE_TENDER_BASELINE_ENABLED=false` 部署 → UI 与本 change 前完全相同
4. 客户验收:找一个真实项目补传 tender + 用户点"立即重新检测" → 确认基线剔除生效
5. 改 `frontend/.env` 设 `VITE_TENDER_BASELINE_ENABLED=true` 重新构建部署
6. 全员可用

**回滚预案(单 commit revert)**:

- 单 commit revert 即可(前后端一起)
- alembic 不主动 downgrade(向后兼容字段保留 NULL,无害)
- 前端 feature flag 关闭立即回退 UI(即使代码部署了)
- 老 `PairComparison.version` 数据未删,自动恢复

**复测**:

- L1 路径:本地新建 project + 上传客户提供模板 zip 作 tender + 4 家应标方,启动检测得 v=1,验证 baseline_source="tender" 段被正确剔除 ironclad
- L2 路径:同 project 不传 tender,3 家应标方,验证 baseline_source="consensus" 段被剔除
- L3 路径:同 project 不传 tender,2 家应标方,验证 UI 警示条 + warnings='baseline_unavailable_low_bidder_count' + Badge 中性灰;**ironclad 触发逻辑保留原行为**(若样本含 ≥50 字 exact_match,text/section 单维度仍 MUST 顶铁证 —— L3 不抑制 ironclad,基线缺失 ≠ 信号无效)
- 回归:跑 `project_id=3297`(`text-sim-exact-match-bypass` 客户演示 zip),版本 v1 不变,新检测 v=2 应识别真抄袭仍铁证(模板段无来源应不剔除)

## Open Questions

- **Q1**:BOQ 工程量精度归一化("1.0" vs "1" vs "1.000")—— 用 `Decimal(str).normalize()` 去尾随零是否足够?是否需要容许误差(±0.1%)?L2 实测调优,本期默认严格相等
- **Q2**:共识 ≥3 是否要按 file_role 分组(每个 role 独立计数)?—— 同一 hash 在 `technical` 标段命中 vs `company_intro` 标段命中语义不同;**design 决:按 file_role 分组**,L1 单测覆盖
- **Q3**:前端启动检测预检查 dialog 何时弹?—— **design 决:仅未传 tender 且未关闭"不再提醒"时弹**;弹的时候提供"不再提醒"checkbox(localStorage 持久化)
- **Q4**:feature flag 解禁后现有项目历史 evidence 立即出 baseline 信息 —— 是否要 backend backfill 一次让历史看着干净?**design 决:不 backfill**,接受过渡期 UI 短暂"baseline=none"展示;新跑 version 自动带新 schema
- **Q5**:tender 解析失败(如 docx 损坏)的兜底 —— **design 决:不阻塞 detector,fail-soft**;`TenderDocument.parse_status='failed'`,baseline_resolver 跳过该 tender,UI 详情页显示"招标文件解析失败,本次检测降级为共识/警示模式"
- **Q6**(R2 H5 揭露):tender 解析是否走 LLM 路径(role_classifier / metadata 抽取)?—— **design 决:不走 LLM**。tender 文件 file_role 固定为 `"tender"`,跳过 `parser/llm/role_classifier.py`;parser pipeline 仅做 docx/xlsx 文本抽取 + segment_hash 计算 + DocumentText/DocumentSheet 入库;**不调用任何 LLM**。理由:① tender 是基线源不是分类目标,role_classifier 对 tender 无意义 ② 避免与 conftest `_disable_l9_llm_by_default` autouse fixture 冲突 ③ 节省 LLM 成本。L1 单测断言 tender 解析全程 0 LLM 调用。
