## Why

C7 `detect-agent-text-similarity` 给出了**整文档**级抄袭命中,但围标场景中常见"只抄某个章节"(如技术方案章节雷同但商务章节独立)。C8 按章节切分后跨投标人对齐比较,能定位到具体章节级证据,给后续人工复核和 Word 导出提供精确锚点。C8 也是 M3 第二个真实 Agent,借此验证 C7 `text_sim_impl` 子包作为"通用文本相似度组件"的可复用性 — 算法不重写,只改粒度。

## What Changes

- **替换 `backend/app/services/detect/agents/section_similarity.py::run()` 为真实实现**(dummy → 真算法);preflight / 注册名 / 签名**零改动**(C6 稳定 contract 锁定)
- 新增 `app/services/detect/agents/section_sim_impl/` 子包,内含:
  - `chapter_parser.py`:纯正则章节切分(`第X章`/`第X节`/`X.Y`/`一、二、`/`数字+空格+标题`五种模式),返 `[ChapterBlock(idx, title, paragraphs)]`
  - `aligner.py`:章节对齐(by title TF-IDF 相似 + 序号回退),返 `[(chapter_a_idx, chapter_b_idx)]` 配对
  - `scorer.py`:对齐后的章节对,调 C7 `text_sim_impl.tfidf.compute_pair_similarity` 算段落对相似度 → 调 C7 `text_sim_impl.llm_judge` 走 LLM 定性 → 调 C7 `text_sim_impl.aggregator` 汇总章节级 score
  - `fallback.py`:章节切分失败的降级分支 → 退化到整文档 TF-IDF(复用 C7 tfidf),但 dimension='section_similarity'、evidence.degraded_to_doc_level=true
- **CPU 密集 sum 走 `get_cpu_executor()`**(复用 C6 D9 接口,与 C7 共享 ProcessPoolExecutor)
- **扩 `tests/fixtures/llm_mock.py`**:`make_section_similarity_response()` 工厂(复用 text_similarity response schema)+ 2 fixture(success / degraded)
- **删除 `section_similarity.py` 对 `_dummy.py` 的引用**,`_dummy.py` 文件保留(其余 8 Agent 仍用)
- **不改任何 contract**:AGENT_REGISTRY key / preflight / AgentContext / AgentRunResult / engine / judge / registry 零改动;`C7 text_sim_impl/` 子包**只读**(一行不改)
- **不引新第三方依赖**:纯正则 + 复用 C7 算法模块(jieba / sklearn / numpy 延续可用)

## Capabilities

### New Capabilities

无(C8 只替换已有 Agent 的 run 实现,不引入新 capability)

### Modified Capabilities

- `detect-framework`:`section_similarity` Agent 从 dummy 替换为真实章节级双轨算法(正则切章 → 对齐 → 复用 C7 tfidf+LLM → 汇总);章节切分失败时降级到整文档粒度(与 C7 独立并行计算,dimension 隔离)

## Impact

- **新代码**:
  - `backend/app/services/detect/agents/section_sim_impl/{__init__,chapter_parser,aligner,scorer,fallback}.py`(5 文件,~400 行)
  - `backend/app/services/detect/agents/section_similarity.py::run()` 重写(~50 行)
- **改动代码**:无(保护层;C7 `text_sim_impl/` 一字不改,仅作 import)
- **新增测试**:
  - `backend/tests/unit/services/detect/agents/section_sim_impl/test_{chapter_parser,aligner,scorer,fallback}.py`(~4 文件,覆盖 5 种章节模式 / 对齐边界 / 复用 C7 算法正确衔接 / 降级路径)
  - `backend/tests/unit/services/detect/agents/test_section_similarity_run.py`(Agent 主流程:Mock LLM + Mock session)
  - `backend/tests/e2e/test_detect_section_similarity.py`(4 scenario 对齐 execution-plan §3 C8 全部:章节雷同 / 章节错位对齐 / 识别失败降级 / 极少章节 skip)
  - `backend/tests/fixtures/llm_mock.py` 新增 1 工厂 + 2 fixture
- **依赖**:**零新增**(C7 `text_sim_impl` 已提供 tfidf/llm_judge/aggregator/stopwords/models/config)
- **环境变量**:新增可选 `SECTION_SIM_MIN_CHAPTERS`(默认 3,章节数 < 此值 preflight skip "章节过少")、`SECTION_SIM_MIN_CHAPTER_CHARS`(默认 100,章节内文本 < 此值该章节合并进前一章节)、`SECTION_SIM_TITLE_ALIGN_THRESHOLD`(默认 0.40,标题 TF-IDF sim ≥ 此值算对齐成功);与 C7 env 并列写入 `backend/README.md`
- **DB**:无表变更;PairComparison.evidence_json 对 `dimension='section_similarity'` 扩一组字段(chapter_pairs / aligned_count / degraded_to_doc_level),与 C7 schema 并列互不冲突
- **回滚**:撤 C8 commit,`section_similarity.py` 恢复 dummy;C7 `text_sim_impl/` 不受影响
- **依赖 change**:C6 detect-framework(框架)+ C7 detect-agent-text-similarity(`text_sim_impl/` 子包复用);C7 归档前 C8 不可实施
