## Why

text_similarity 在客户实测场景下漏识别"用户故意复制粘贴的相同段"。2026-04-29 演示文件 A、C 各贴 3 段(165/131/47 字),系统判 92/100 高风险,但"双栏对比"UI 没高亮 3 段——展示效果不及预期,削弱产品说服力。

根因双锁:

- 段长 < 50 触发 `_merge_short_paragraphs` 的 buf 累积合并,A、C 合并段尾内容不同 → cosine 远低于 1.0(165 字=0.93,47 字=0.81)
- 即使段独立成段,A↔C 真模板段(国家监理规范条款 28 对) cosine ≥ 0.99 占满 `MAX_PAIRS_TO_LLM=30` 上限,注入段排 31~102 名被截断,LLM 不见 → evidence 不收录

数学第一性原理:TF-IDF 中两段 token 序列完全一致时 cosine 必然 = 1.0(IDF 是全局缩放对夹角不变)。问题不在算法,在 segmenter 的 buf 累积合并 + top 30 cap 双重作用。

**本次为过渡方案**:仅救"100% 字符复制"场景。改 1 字的近似抄袭后续走 ngram / MinHash / shingle 演进(留 v2,记入 `docs/handoff.md` 演进路径条目)。

## What Changes

- `tfidf.compute_pair_similarity` 入口前加段级 hash 精确匹配旁路:归一化(去首尾空白 + 合并连续空白 + Unicode NFKC) + sha1 hash;A、C 之间字符 100% 相同的段对绕开 cosine 排名直接进 evidence top
- `MAX_PAIRS_TO_LLM` 默认 30 → 80,救 cosine 0.95~0.99 的"改字近似抄袭"
- `evidence_json.samples` 新增 `label='exact_match'`,区分于 plagiarism / template / generic
- `ironclad`(铁证)收紧:`exact_match` 段仅在归一化后字符长度 ≥ 50 时触发,避免业主名 / 项目名 / 章节标题等通用短段误升铁证

总分参与与去重口径(避免回归):

- hash 命中段对在 `aggregate_pair_score` 中按 sim=1.0 等权计入(与 plagiarism 段同权)
- hash 命中段不送 LLM judge 复评,label 直接定为 `exact_match`,节省 token
- cosine top 80 候选集排除已 hash 命中的 `(a_idx, b_idx)` 对,避免双计

Label 互斥优先级:同一段对 `exact_match > plagiarism > template > generic`;hash 命中即终态,不再 LLM 复评。UI 颜色 / 文案 / 铁证标识差异在 design 定义。

## Capabilities

### New Capabilities

(无)

### Modified Capabilities

- `detect-framework`: text_similarity 维度增加精确匹配旁路 + 总分参与口径调整 + ironclad 长度门槛 + label 互斥优先级

## Impact

- **后端代码**: `backend/app/services/detect/agents/text_sim_impl/{tfidf,config,aggregator,models}.py`
- **数据**: 仅 `evidence_json` 字段扩展,无表结构变更
- **前端**: 不变(UI 按 sample 自动渲染;旧 evidence 无 `exact_match` label 的容错 fallback 在 design 评估)

**Score 数值口径变化(历史不可比)**: 新算法对模板化文档复跑会显著抬升 aggregate score(短串归一化后命中量大 + cap 80 双叠加),现存项目历史 score 与新版本不可比。迁移 / 重算 / 版本化(`PairComparison.version` 字段已有)策略放 design。

**LLM 调用 / 性能风险**(必须在 design 量化评估,不在 proposal 决策):

- cap 30→80: prompt + response token 各涨 ~2.7x
- 单次 LLM 请求估 ~16K token,接近 8K / 32K 主流上下文窗口边界,需实测
- 兜底: 若实测溢出,降级路径在 design 评估(候选: 动态 cap 回退 / 分批 LLM / fail-soft 跳过)
- text_similarity agent 单维度耗时拉长 → 拖累 SSE 进度条 + demo 体感
- `evidence_json.samples` 数组从 30 → 80 → 前端 JSON 解析 / 渲染压力
- **缓解**: hash 命中段不进 LLM,实际增量受文档模板化程度影响

**复测**: 本地 `project_id=3296` + NEW demo zip(`tmp_repro2/同样句式加在第一段/`)。

**不破坏**: 现有 28 对真模板段 plagiarism / template / generic 判定流程。
