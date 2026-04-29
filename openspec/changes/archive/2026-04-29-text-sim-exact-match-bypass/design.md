## Context

`text_similarity` agent 现状: 本地 TF-IDF 筛 + LLM judge 双轨。关键参数:

- `MIN_PARAGRAPH_CHARS = 50` (短段合并阈值)
- `PAIR_SCORE_THRESHOLD = 0.70` (cosine 入选)
- `MAX_PAIRS_TO_LLM = 30` (top 30 给 LLM)

2026-04-29 客户演示用真实文件实证: A、C 各贴 3 段(165/131/47 字)字符 100% 相同,但全部漏识别。根因双锁:

- (i) 47 字 < 50 触发 `_merge_short_paragraphs` 的 buf 累积合并,A、C 合并段尾不同 → cosine 0.81
- (ii) 真模板段 28 对 cosine ≥ 0.9925 占满 top 30 → 165/131 字注入段排 31~57 名被截断

proposal 已确认产品语义(总分口径、去重、label 优先级、ironclad 长度门槛、过渡性);spec 已确认行为契约(三轨分工、SHALL/MUST、scenario 覆盖)。本 design 解决"如何实施"。

## Goals / Non-Goals

**Goals:**

- ≤ 30 行核心代码内,让字符 100% 相同的段对绕开 cosine 排名直接进 evidence top
- `MAX_PAIRS_TO_LLM` 30 → 80,救 cosine 0.95~0.99 的近似抄袭
- ironclad 加 ≥ 50 字门槛防业主名/项目名误升铁证
- evidence_json 向前兼容(旧版本前端不抛错)
- 零 schema migration,无数据库 alembic 升级

**Non-Goals:**

- 不重写 TF-IDF 算法
- 不做 ngram / MinHash / shingle (留 v2,记入 `docs/handoff.md` 演进路径)
- 不改前端 / 不改 LLM judge prompt / 不改 segmenter
- 不动 PairComparison 表结构

## Decisions

### D1: 归一化策略 = NFKC + `\s+` 合并 + strip

**选**: `unicodedata.normalize('NFKC', t)` → `re.sub(r'\s+', ' ', t)` → `.strip()`

**备选 A 不选**: `casefold()` — 中文无大小写,反让数字字母混淆
**备选 B 不选**: 标点全部剥离 — 过激,改变语义,真抄袭也常改标点

**理由**: NFKC 正好处理全角半角(常见 Word 复制场景);`\s+` 处理"复制时多/少打空格";`strip()` 处理粘贴时首尾换行。语义保留充分,误等价风险低。

### D2: Hash 算法 = sha1(可换 blake2b/xxhash,非密码学需求)

**选**: `hashlib.sha1` 标准库,40 字符 hexdigest

**备选**: `blake2b`(更快但 56 位)/ `xxhash`(最快但需新依赖)

**理由**: 段数级别 N+M 调用,sha1 性能足够(微秒级);零新依赖;spec 已注脚未来可换。

### D3: 旁路集成位置 = `tfidf.compute_pair_similarity` 入口前

**选**: 新函数 `_hash_pairs(paras_a, paras_b) -> tuple[list[ParaPair], set[tuple[int,int]]]`,在 `fit_transform` 之前调用,返 (命中 pair 列表, 已命中索引集合)

**备选**: 在 `segmenter.py` 内集成 — 过早,跨 agent 影响 `section_similarity`,scope 失控

**理由**: 入口前注入最小侵入,只 `text_similarity` 受影响;命中 pair 直接拼到 cosine 结果集前。

### D4: cosine 候选集排除已命中对

**选**: TF-IDF 矩阵 `enumerate (i, j)` 时 `if (i, j) in hit_set: continue`

**备选**: 重置 `sim_matrix[i, j] = 0` — 改矩阵副作用大,影响其它 enum

**理由**: O(1) 集合查询,不动矩阵,语义清晰;hits 与 cosine 结果合并后统一按 sim 降序截 cap。

### D5: cap 30→80 溢出兜底 = 动态降级

**选**: LLM judge 调用前 `_estimate_prompt_tokens(pairs)`(简单按 a_text + b_text 字符数 / 1.5 估算 token);若超 24K(给 response 留 8K,主流模型 32K 上限)按 sim 降序 truncate 到 ≤24K;truncate 计入 `evidence_json.degraded_reason = 'token_overflow'`(degraded 仍 false,只是 prompt 被裁剪)

**备选 A**: 分批 LLM (N 次小请求) — 多倍延迟,SSE 进度条更糟
**备选 B**: fail-soft 全部降级 — 牺牲所有 plagiarism 判定过激

**理由**: token 估算成本 ~ms 级;truncate 时按 sim 降序保高质量 pair;evidence 留痕便于排查。具体 24K 阈值待 L3 实测调优(见 Open Questions Q1)。

### D6: score drift 迁移 = `PairComparison.version` 字段已有,自然递增

**选**: 新算法跑出 `version = N+1` 行,旧 `version = N` 行保留只读;前端 URL `/reports/{project_id}/{version}` 已支持按 version 取数;UI 默认展示 max version,用户可通过 URL 访问历史 version

**备选**: 数据库强迁移(SQL 重算所有历史 score)— 不可逆,出问题难回滚

**已验证依据**:

- `PairComparison.version: Integer NOT NULL` 字段已存在(`pair_comparison.py:41`)
- 复合索引 `(project_id, version, dimension)` 已存在
- 启动检测时 `max(AgentTask.version) + 1` 自动递增(`analysis.py:134`)
- 报告 API 三处按 `(project_id, version)` 取数(`reports.py:86, 220, 296`)
- 前端 URL `/reports/3296/1` 形式已上线

**理由**: 零 migration,零数据迁移,客户向用户解释自然("上周 78 分基于旧算法 v1,本周 89 分基于新算法 v2,历史可查")。新代码部署后用户主动点"启动检测"才会跑新算法。

### D7: 旧 evidence label fallback = 前端 1 行容错

**选**: 前端 sample.label 缺失或不在已知枚举时按 `'generic'` 渲染色;具体落点 `frontend/src/pages/CompareView.tsx`(或同等组件)

**备选**: 后端补迁移 SQL 给历史行加 `label='generic'` — 无意义改动量大

**理由**: 前端 1 行 JS `||` 容错,旧数据 0 改动。

### D8: ironclad 长度判定 = 归一化后字符长度

**选**: `aggregator.compute_is_ironclad` 收 hits 时,对每个 hit 算 `len(_normalize(a_text)) >= 50` 才纳入 ironclad 触发集

**备选**: 用 raw 字符长度 — 全角空格等会人为推高,与 hash 比对口径不一致

**理由**: 与 hash 比对的归一化口径统一,无双重标准;且复用同一 `_normalize` 函数。

### D9: hash 命中段在 LLM judge prompt 中"是否提示"

**选**: **不提**,prompt 保持只对 cosine 候选(≤80 段)负责

**备选**: prompt 加一段 "已识别 N 段为完全相同复制粘贴,请重点判定剩余近似段" — prompt 膨胀,且 LLM 可能误把"已识别"段也复评影响一致性

**理由**: 职责单一原则;hash 旁路是确定性结果不需要 LLM 验证;LLM 资源全用于 cosine 候选段的定性。

## Risks / Trade-offs

| Risk | Mitigation |
|---|---|
| Score 数值口径变化, 历史项目复跑结果与归档不可比 | D6: PairComparison.version 自然递增, UI 路由按 version 展示, URL 可访问历史 |
| LLM 单请求溢出 8K/32K 上下文窗口 | D5: 动态 token 估算 + truncate + evidence 留痕 |
| evidence_json.samples 80 段 ~40 KB 前端解析压力 | 已评估在 PG JSONB 容忍范围(≤ 40 KB);前端可分页加载留 v2 |
| SSE 进度条因 LLM 耗时拉长体感掉分 | hash 命中段免 LLM 抵消大部分增量;实测 demo 体感在 L3 截图归档 |
| "复制 + 改 1 字" hash 救不了 | proposal 已显式承认过渡性,ngram/MinHash v2 路径已留(handoff) |
| 测试遗留 `test_aggregator.py:137 == 30` 假设 | tasks `[impl]` 任务中显式同步为 80 |
| `_normalize` 归一化在某些 Unicode 边界(组合字符)等价但视觉不同 | NFKC 已是组合字符规范化形式,边界 case 在 L1 单测中覆盖 |

## Migration Plan

**单步部署**: 仅后端代码改动,无 schema migration,无 alembic 升级。

**部署流程**:

1. 合并 PR + 部署后端(`backend/app/services/detect/agents/text_sim_impl/{tfidf,config,aggregator,models}.py` 改动)
2. 历史 PairComparison 行不变(version=N 保留只读)
3. 用户主动点"启动检测"触发跑新算法 → 写出 version=N+1 行
4. 前端默认展示 max version,UI 自动呈现新算法结果

**回滚**: 单 commit revert,version=N 行未删自动恢复;version=N+1 行保留(数据无破坏,仅为废弃版本)。

**复测**: 用本地 `project_id=3296` (bidder A=3720, C=3721) 重传 NEW demo zip(`tmp_repro2/同样句式加在第一段/`),启动新检测得 version=2,L3 截图证明:

- 双栏 UI 三段全部高亮(165/131/47 字)
- 原 28 对真模板段 plagiarism / template 判定不变(回归保护)
- evidence_json.pairs_exact_match ≥ 3

## Open Questions

- **Q1**: D5 token 估算阈值 24K 是基于"主流 32K 模型留 8K response"反推的工程值,具体阈值待 L3 实测后调优(可能因 LLM 模型 8K / 32K / 100K 不同而需配置化)
- **Q2**: 客户演示场景下"hash 旁路命中"在 UI 上是否需要单独 badge 区分(如 "100% 相同" vs "近似抄袭")? 本 design 决: 暂不加,沿用现有 plagiarism 渲染色;若产品后续要求再加 v2
- **Q3**: hash 旁路是否对 segmenter 合并后的"超长段"(>1000 字)有性能担忧? 估算: sha1 单段 < 1ms,N+M 段总 < 10ms,可忽略
