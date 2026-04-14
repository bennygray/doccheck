## 1. section_sim_impl 子包骨架

- [x] 1.1 [impl] 新建 `backend/app/services/detect/agents/section_sim_impl/__init__.py`
- [x] 1.2 [impl] 新建 `section_sim_impl/config.py`:动态读 3 env(`SECTION_SIM_MIN_CHAPTERS / _MIN_CHAPTER_CHARS / _TITLE_ALIGN_THRESHOLD`)
- [x] 1.3 [impl] 新建 `section_sim_impl/models.py`:`ChapterBlock / ChapterPair / ChapterScoreResult` dataclass

## 2. 章节切分(chapter_parser)

- [x] 2.1 [impl] 新建 `chapter_parser.py`:5 种 PATTERN(第X章/第X节/X.Y数字/中文数字+顿号/纯数字+顿号)+ `_is_chapter_title`
- [x] 2.2 [impl] `extract_chapters(paragraphs, min_chapter_chars) -> list[ChapterBlock]`:遍历段落,命中 PATTERN → 开启新 ChapterBlock;短章节合并进前一章节
- [x] 2.3 [impl] 边界处理:空输入 / 无命中 / 标题行后无正文(下章节的 title 吸收)
- [x] 2.4 [L1] `test_chapter_parser.py`:19 用例,覆盖 5 PATTERN + 非标题行 + 空/无命中/标准三章节/短合并/无内容章节/封面忽略/超长 title 截断

## 3. 章节对齐(aligner)

- [x] 3.1 [impl] 新建 `aligner.py`:`align_chapters(a, b, threshold) -> list[ChapterPair]`
- [x] 3.2 [impl] `_title_tokenizer`(比 C7 body tokenizer 宽松,不去 STOPWORDS,保留"投标/项目"等短 title 区分词)+ TfidfVectorizer 计算 |a|×|b| 矩阵 + 贪心配对
- [x] 3.3 [impl] 未配对走 idx 序号回退;返 list 长度 = min(|a|, |b|);多余丢弃
- [x] 3.4 [L1] `test_aligner.py`:7 用例,覆盖空侧 / 完美对齐 / title reorder / 全 index 回退 / partial / 多余丢弃 / 近义 title

## 4. 章节评分(scorer,复用 C7)

- [x] 4.1 [impl] 新建 `scorer.py`:`score_all_chapter_pairs(chapters_a, chapters_b, chapter_pairs, llm, names, doc_role) -> (results, selected, judgments, ai_meta)`
- [x] 4.2 [impl] 对每对章节 `run_in_executor(get_cpu_executor(), c7_tfidf.compute_pair_similarity)` 算段落对;合并所有段落对按 `title_sim × sim` 粗排截 MAX_PAIRS_TO_LLM
- [x] 4.3 [impl] 合并一次 LLM 调用(`c7_llm_judge.call_llm_judge`);章节级 chapter_score / is_chapter_ironclad 回落(本章节 selected 中的 judgments + 未 selected 按 None 权重)
- [x] 4.4 [impl] `aggregate_pair_level(results) -> (score, is_ironclad)`:max*0.6 + mean*0.4,any(ironclad)
- [x] 4.5 [L1] `test_scorer.py`:5 用例,覆盖空对 / 复用 C7 模块验证 / LLM timeout 降级 / aggregate 空 / max-mean 加权

## 5. 降级分支(fallback)

- [x] 5.1 [impl] 新建 `fallback.py`:`async run_doc_level_fallback(paras_a, paras_b, ...) -> (score, is_ironclad, evidence)` 直接复用 C7 tfidf/llm_judge/aggregator
- [x] 5.2 [impl] evidence.algorithm="tfidf_cosine_fallback_to_doc" + degraded_to_doc_level=true + degrade_reason
- [x] 5.3 [L1] `test_fallback.py`:3 用例,正常 LLM success / 双重降级(切章 + LLM timeout)/ 空段对 0 分

## 6. section_similarity.py::run() 真实实现

- [x] 6.1 [impl] preflight 扩 "双方 total_chars ≥ 500"(复用 C7 TEXT_SIM_MIN_DOC_CHARS)
- [x] 6.2 [impl] run() 5 步:role 选择 + raw body 段落加载 → 正则切章 → 切分判定(成功/失败分支)→ align → score → aggregate → INSERT PairComparison
- [x] 6.3 [impl] **关键改动**:新增 `section_sim_impl/raw_loader.py`,C8 章节级**绕过 C7 segmenter 的短段合并**(segmenter 合并会把短标题粘到 body,破坏章节边界);C7 segmenter 零改动
- [x] 6.4 [impl] 删除 `_dummy.py` 引用;evidence_json 按 design D7 构造章节字段 + C7 兼容字段
- [x] 6.5 [L1] `test_section_similarity_run.py`:6 用例,preflight 3 场景 + run 正常 + run 降级(章节数不足) + chapter 模式 + LLM timeout

## 7. LLM mock fixture 扩展

- [x] 7.1 [impl] `llm_mock.py` 新增 `make_section_similarity_response()` 工厂(复用 C7 response schema,单独命名便于语义区分)
- [x] 7.2 [impl] 新增 2 fixture:`mock_llm_section_sim_success` / `mock_llm_section_sim_degraded`

## 8. E2E 真实检测链路(L2)

- [x] 8.1 [impl] `tests/e2e/test_detect_section_similarity.py`:`_seed_project_and_bidders` helper + `_mk_chapter` 辅助 + 标准 3 章节文档生成器
- [x] 8.2 [L2] scenario 1 "章节雷同命中":3 章节双方全同 → score ≥ 60 + is_ironclad + chapter_pairs ≥ 1 铁证
- [x] 8.3 [L2] scenario 2 "章节错位对齐":A 5 章节 B 4 章节,"技术方案"在 a_idx=2/b_idx=3 → aligned_by='title' 成功对齐
- [x] 8.4 [L2] scenario 3 "识别失败降级":双方无 PATTERN 命中 → evidence.degraded_to_doc_level=true
- [x] 8.5 [L2] scenario 4 "极少章节降级":A 1 章节(< 3)→ 降级路径,status succeeded

## 9. 环境变量与文档

- [x] 9.1 [impl] `backend/README.md` 新增 "C8 detect-agent-section-similarity 依赖" 段
- [x] 9.2 [impl] 3 env 由 `section_sim_impl/config.py` 独立读取

## 10. L3 UI 验证(降级手工凭证)

- [x] 10.1 [L3] Docker kernel-lock 未解 → 手工降级
- [x] 10.2 [manual] `e2e/artifacts/c8-2026-04-15/README.md` 占位 + 3 张截图计划 + `.gitignore` 加 c8-* 白名单

## 11. 自检与归档前校验

- [x] 11.1 [impl] `ruff check backend/` — C8 scope 全绿
- [x] 11.2 [impl] C6 contract + C7 `text_sim_impl/` 零改动:7 C7 文件无 diff;其他 8 Agent 文件无 diff(C7 text_similarity.py 和 engine.py 都不动);registry.py/judge.py/context.py 无 diff
- [x] 11.3 [impl] `_dummy.py` 保留(8 Agent 仍用);section_similarity.py 不再 import `_dummy`
- [x] 11.4 [x] 跑 [L1][L2][L3] 全部测试,全绿(L1 266 / L2 182 / L3 手工凭证 = 448 pass;C8 新增 38 用例)
