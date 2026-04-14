## Why

C6 `detect-framework` 已把 10 Agent 框架铺通,10 个 `run()` 全部 dummy(随机分+sleep)。M3 检测维度真实落地从 C7 开始 — 文本相似度 Agent 是最核心且覆盖面最广的"围标抄袭"识别手段,且其双轨算法(本地向量筛 + LLM 定性)直接复用一次后可被 C8/C9 沿用,C7 也是 `get_cpu_executor()` 的第一个真消费者,借此验证 ProcessPoolExecutor 在真实 Agent 下的健壮性(executor cancel / 容器 cpu_count 两个 C6 留下的 TODO)。

## What Changes

- **替换 `backend/app/services/detect/agents/text_similarity.py::run()` 为真实实现**(dummy → 真算法);preflight / 注册名 / 参数签名**零改动**(C6 稳定 contract 锁定)
- 新增 `app/services/detect/agents/text_sim_impl/` 子包,内含:
  - `segmenter.py`:docx 原生段落切分 + 短段落合并 + 超短文档识别
  - `tfidf.py`:jieba 中文分词 + `TfidfVectorizer + cosine_similarity` 段落对打分
  - `llm_judge.py`:按 L-4 规格组 prompt + 调 `ctx.llm_provider` + 严格 JSON 解析 + 1 次重试
  - `aggregator.py`:段落对分数汇总 → PairComparison.score(整体 pair 级) + is_ironclad 判定
- **CPU 密集计算走 `get_cpu_executor() + loop.run_in_executor()`**(C6 Risk-1 真消费者首验)
- **扩 `tests/fixtures/llm_mock.py`**:新增 `make_text_similarity_response()` 工厂 + 3 个 fixture(success / bad_json / timeout)
- **删除 `text_similarity` 对 `_dummy.py` 的引用**(但 `_dummy.py` 文件保留,其余 9 个 dummy Agent 仍引用)
- **不改任何 contract**:AGENT_REGISTRY key / preflight / AgentContext / AgentRunResult / engine / judge / registry 零改动
- **不引新第三方依赖**:`jieba / scikit-learn / numpy` C5 已引入,直接复用

## Capabilities

### New Capabilities

无(C7 只替换已有 Agent 的 run 实现,不引入新 capability)

### Modified Capabilities

- `detect-framework`:`text_similarity` Agent 从 dummy 替换为真实双轨算法(本地 TF-IDF + cosine 筛段落对 → LLM 定性 template/generic/plagiarism → 汇总 score + is_ironclad);注册 key / preflight / 返回类型保持 C6 定义

## Impact

- **新代码**:
  - `backend/app/services/detect/agents/text_sim_impl/{__init__,segmenter,tfidf,llm_judge,aggregator}.py`(~5 文件,~500 行)
  - `backend/app/services/detect/agents/text_similarity.py::run()` 重写(~40 行)
- **改动代码**:无(保护层)
- **新增测试**:
  - `backend/tests/unit/services/detect/agents/text_sim_impl/test_*.py`(~5 文件,覆盖分块/TF-IDF/LLM parse/aggregator/superficial edge cases)
  - `backend/tests/unit/services/detect/agents/test_text_similarity_run.py`(Agent 主流程单测,Mock LLM + Mock session)
  - `backend/tests/e2e/test_detect_text_similarity.py`(完整 E2E:启动检测 → 真实 text_similarity 跑完 → 验证 PairComparison 行 + AgentTask.score)
  - `backend/tests/fixtures/llm_mock.py` 新增 3 fixture + 1 工厂
- **依赖**:**零新增**。`jieba / scikit-learn / numpy` C5 parser-pipeline 已引入;`ctx.llm_provider` C6 已预留
- **环境变量**:新增可选 `TEXT_SIM_MIN_DOC_CHARS`(默认 500,短于此值文档 preflight skip)、`TEXT_SIM_PAIR_SCORE_THRESHOLD`(默认 0.70,段落对超此值才送 LLM)、`TEXT_SIM_MAX_PAIRS_TO_LLM`(默认 30,每 pair 最多发 30 段对给 LLM 防 token 爆炸),与 C5/C6 env 并列写入 `backend/README.md`
- **DB**:无表变更(PairComparison.evidence_json 复用,结构由 aggregator 约定)
- **回滚**:撤 C7 commit 即可;框架 + 其余 9 Agent dummy 不动
- **依赖 change**:C6 detect-framework(已归档)提供框架;C5 parser-pipeline 提供 `DocumentText` 表(内容源)+ LLM 适配层
