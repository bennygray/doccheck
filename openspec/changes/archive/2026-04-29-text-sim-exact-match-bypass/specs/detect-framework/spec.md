## MODIFIED Requirements

### Requirement: text_similarity 双轨算法(本地 TF-IDF + LLM 定性)

Agent `text_similarity` 的 `run()` MUST 采用三轨分工(段级 hash 旁路 + 本地 TF-IDF + LLM 定性):

0. **段级 hash 精确匹配旁路**(始终前置执行):见『text_similarity 段级 hash 精确匹配旁路』需求。命中段对 MUST 以 sim=1.0、label='exact_match' 进入结果集,且 MUST NOT 参与 TF-IDF 排名,MUST NOT 送 LLM judge。

1. **本地 TF-IDF 筛选**(始终执行):
   - 取双方同角色文档的段落列表(优先 `技术方案`,无则回退 `商务`、`其他`)
   - jieba 分词 + 去停用词 + `TfidfVectorizer(ngram_range=(1, 2), min_df=1, max_df=0.95, max_features=20000)`
   - `cosine_similarity(mat_a, mat_b)` 构造段落对相似度矩阵
   - 取 `sim >= TEXT_SIM_PAIR_SCORE_THRESHOLD`(默认 0.70)的段落对,候选集 MUST 排除已 hash 命中的 `(a_idx, b_idx)` 对
   - 按 sim 降序截取前 `TEXT_SIM_MAX_PAIRS_TO_LLM`(默认 60,旧值 30;L3 实测 80 在大模板化文档下触发 LLM 300s timeout,折中到 60)条

2. **LLM 定性判定**(超阈值段落对存在时执行):
   - 按 requirements.md §10.8 L-4 规格组 prompt:输入双方名称、文档角色、段落对列表(含文本和程序相似度)
   - 请求 LLM 返回 JSON:每对段落 `judgment ∈ {template, generic, plagiarism}` + 整体 `overall` + `confidence ∈ {high, medium, low}`
   - 严格 JSON 解析;失败 → 重试 1 次;仍失败 → 降级

3. **score 汇总**:每对 `score_i = sim * 100 * W[label]`,其中 `W = {exact_match: 1.0, plagiarism: 1.0, template: 0.6, generic: 0.2, None(降级): 0.3}`;pair 级 `score = round(max(scored) * 0.7 + mean(scored) * 0.3, 2)`

4. **is_ironclad 判定**:见『text_similarity exact_match label 优先级与 ironclad 长度门槛』需求(自包含完整规则)。

CPU 密集步骤(TF-IDF 向量化 + cosine 计算)MUST 走 `get_cpu_executor()` + `loop.run_in_executor()`,不阻塞 event loop;hash 旁路计算量小,可主协程内同步执行。

#### Scenario: 抄袭样本高分命中

- **WHEN** pair(A, B)双方技术方案段落包含 ≥ 5 段几乎逐字相同的文本,LLM 返回全部 plagiarism
- **THEN** PairComparison.score ≥ 85.0,is_ironclad = True,evidence_json.pairs_plagiarism ≥ 5

#### Scenario: 完全字符复制段命中 hash 旁路

- **WHEN** pair(A, B)双方技术方案中存在归一化后字符 100% 相同的段(如复制粘贴的 165 字段)
- **THEN** 该段对 MUST 以 sim=1.0、label='exact_match' 进入 evidence_json.samples;且 MUST NOT 送 LLM judge

#### Scenario: 独立样本低分不误报

- **WHEN** pair(A, B)双方文档独立撰写,TF-IDF 筛选无段落对 sim ≥ 0.70,且 hash 旁路无命中
- **THEN** PairComparison.score < 20.0,is_ironclad = False,evidence_json.pairs_total = 0,LLM 未被调用

#### Scenario: 三份中一对命中

- **WHEN** 3 家 bidder 中仅 (A, B) 对抄袭,(A, C) 和 (B, C) 独立
- **THEN** pair(A,B).score 高 + is_ironclad=True;pair(A,C) / (B,C) score 低 + is_ironclad=False

#### Scenario: 段落对 sim 超阈值但 LLM 判为 generic

- **WHEN** LLM 返回全部段落对 judgment = generic(行业通用表述)
- **THEN** PairComparison.score 按 generic 权重 0.2 折算;is_ironclad = False

#### Scenario: TF-IDF 候选集排除已 hash 命中段对避免双计

- **WHEN** A[i] 与 B[j] 已被 hash 旁路命中
- **THEN** TF-IDF 候选集 MUST 排除 (i, j),evidence_json.samples 中该对 MUST 仅以 label='exact_match' 出现一次

---

### Requirement: text_similarity evidence_json 结构

`PairComparison.evidence_json` 对 `dimension = 'text_similarity'` 的行 MUST 包含以下字段:

| 字段 | 类型 | 说明 |
|---|---|---|
| `algorithm` | string | 固定 `"tfidf_cosine_v1"`,区分 dummy |
| `doc_role` | string | 实际比对的文档角色 |
| `doc_id_a` / `doc_id_b` | int | 被比对的 BidDocument id |
| `threshold` | float | 本次 TEXT_SIM_PAIR_SCORE_THRESHOLD 实际值 |
| `pairs_total` | int | 段落对总数(hash 命中 + cosine 超阈值,**不重复计数**) |
| `pairs_exact_match` | int | hash 旁路命中段对数(新增字段) |
| `pairs_plagiarism` | int | LLM 判 plagiarism 段数(降级模式 = 0) |
| `pairs_template` | int | LLM 判 template 段数(降级模式 = 0) |
| `pairs_generic` | int | LLM 判 generic 段数(降级模式 = pairs_total - pairs_exact_match) |
| `degraded` | bool | LLM 是否降级 |
| `ai_judgment` | object/null | `{overall: string, confidence: string}`,降级时 null |
| `samples` | array | 按 sim 降序前 N 条 `{a_idx, b_idx, a_text, b_text, sim, label, note}`,其中 `label ∈ {exact_match, plagiarism, template, generic}` |

`samples` 上限 N MUST = 60(spec 旧值 10 与代码现实 30 已不一致,本次同步统一为 60;与 cap 联动);`a_text` / `b_text` 每条最多截取 200 字符。
单行 evidence_json MUST ≤ ~32 KB(60 段 × ~530 字节),在 PG JSONB 容忍范围内,无需 TOAST 拆分。

旧版 evidence_json(无 `pairs_exact_match` 字段或 `samples.label='exact_match'` 取值)前端 SHALL 按 `label='generic'` 容错降级渲染,MUST NOT 抛错。

#### Scenario: 正常 evidence_json 结构

- **WHEN** text_similarity 正常完成(LLM 成功)
- **THEN** evidence_json 含 algorithm="tfidf_cosine_v1" + ai_judgment 非 null + samples ≤ 60

#### Scenario: 含 hash 命中的 evidence_json 结构

- **WHEN** text_similarity 命中 ≥ 1 段 hash 旁路 + LLM 正常完成
- **THEN** evidence_json.pairs_exact_match ≥ 1,samples 中 ≥ 1 条 label='exact_match' 且 sim=1.0

#### Scenario: 降级 evidence_json 结构

- **WHEN** text_similarity LLM 降级完成
- **THEN** evidence_json.degraded=true + ai_judgment=null + samples 仍有(程序相似度 + hash 命中段保留;label='exact_match' 段不受 LLM 降级影响)

---

## ADDED Requirements

### Requirement: text_similarity 段级 hash 精确匹配旁路

Agent `text_similarity` MUST 在 TF-IDF 计算前先执行段级 hash 精确匹配,识别字符 100% 相同的段对(用户故意复制粘贴 / 整段抄袭场景):

1. **归一化函数 `_normalize(text)`**:对每段依次执行
   - `unicodedata.normalize('NFKC', text)` 统一全角半角
   - `re.sub(r'\s+', ' ', text)` 合并连续空白为单空格
   - `text.strip()` 去首尾空白

2. **Hash 比对**:
   - 对 A、B 双方所有 segmenter 合并后段做 `hashlib.sha1(_normalize(text).encode('utf-8')).hexdigest()`
   - 分别构建 `{hash: [a_idx]}` / `{hash: [b_idx]}` 索引
   - 对所有共有 hash 取笛卡尔积 `(a_idx, b_idx)` 命中对

3. **命中处理**:
   - 命中对 MUST 以 sim=1.0、label='exact_match' 直接构造 `ParaPair`
   - `a_text` / `b_text` MUST 取归一化前的原始字符串(截断 200 字符)
   - 命中对 `(a_idx, b_idx)` MUST 从后续 cosine 候选集中排除
   - 命中对 MUST NOT 送 LLM judge 复评

4. **算法语义注脚**:`hashlib.sha1` 仅作统一比较键,**非密码学需求**;实施可用更轻的 `blake2b` / `xxhash` 替换,不影响行为契约。

#### Scenario: 完全字符复制段命中

- **WHEN** A 段 "检查材料的保管情况:..."(165 字)与 B 段同一字符串完全相同
- **THEN** hash 旁路 MUST 命中,evidence.samples 含该对 sim=1.0、label='exact_match'

#### Scenario: 全角半角等价归一化

- **WHEN** A 段含全角逗号 "投标方,联系人",B 段含半角逗号 "投标方,联系人",其余字符相同
- **THEN** NFKC 归一化后两段 hash MUST 相同,旁路命中

#### Scenario: 连续空白归一化

- **WHEN** A 段含 "施工  方案"(双空格),B 段含 "施工 方案"(单空格)
- **THEN** `\s+` 合并后两段 hash MUST 相同,旁路命中

#### Scenario: 命中段不参与 cosine 候选

- **WHEN** A[i]、B[j] 已被 hash 命中,且其在 cosine 矩阵中也 sim=1.0
- **THEN** TF-IDF 候选集 MUST 排除 (i, j),不送 LLM,避免双计

---

### Requirement: text_similarity exact_match label 优先级与 ironclad 长度门槛

Agent `text_similarity` MUST 实施 label 互斥优先级与 ironclad 长度门槛(自包含完整规则):

1. **Label 互斥优先级**(从高到低):`exact_match > plagiarism > template > generic`
   - hash 旁路命中段 label MUST 直接定为 `exact_match`,即终态,MUST NOT 由 LLM 二次覆写
   - LLM 返回的 plagiarism / template / generic 仅适用于 cosine 候选段(MUST 不含 hash 命中段)

2. **Score 权重**:`W[exact_match] = 1.0`(与 plagiarism 同权,sim=1.0 时 `score_i = 100`)

3. **is_ironclad 完整判定**(LLM 非降级模式下,以下任一条件 MUST → True):
   - `pairs_plagiarism >= 3`
   - `pairs_plagiarism / pairs_total >= 0.5`
   - `pairs_exact_match` 中**含 ≥ 1 段归一化后字符长度 ≥ 50**
   - 否则 MUST = False

4. **降级模式**:LLM 降级时 `is_ironclad` MUST 始终 = False,**包括** evidence 中含 ≥ 1 段 ≥ 50 字 exact_match 的情况

5. **< 50 字 exact_match**:MUST 计入 score(权重 1.0),MUST NOT 单独触发 ironclad

#### Scenario: 50 字 exact_match 升 ironclad

- **WHEN** evidence_json.samples 含 ≥ 1 条 label='exact_match' 且归一化后 a_text 字符长度 ≥ 50
- **THEN** is_ironclad MUST = True

#### Scenario: 49 字 exact_match 不升 ironclad

- **WHEN** evidence_json.samples 含的 exact_match 段归一化后字符均 < 50(如业主名 12 字、项目名 19 字)
- **THEN** is_ironclad MUST = False(除非另有 pairs_plagiarism ≥ 3 或 ≥ 50% 触发)

#### Scenario: hash 命中段 label 不被 LLM 二次覆写

- **WHEN** A[i]、B[j] 字符 100% 相同被 hash 命中,LLM 同时在另一独立 cosine 候选 (k, l) 上判 plagiarism
- **THEN** (i, j) label MUST = 'exact_match',(k, l) label = 'plagiarism';两类同存,LLM 判定 MUST NOT 覆盖 (i, j)

#### Scenario: 降级模式下 exact_match 不升 ironclad

- **WHEN** LLM 降级 + hash 命中 1 段 ≥ 50 字 exact_match
- **THEN** evidence_json.degraded MUST = true,is_ironclad MUST = False(降级永远 False,即使 exact_match)
