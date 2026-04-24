## 1. 实现:role_classifier.py 3 条日志 + mojibake helper

- [x] 1.1 [impl] 在 `backend/app/services/parser/llm/role_classifier.py` 模块顶层新增私有 `_looks_mojibake(name: str) -> bool` heuristic(按 D4 的 MARKERS 常量 + `any(m in name for m in MARKERS)` 粗判);空串返 False
- [x] 1.2 [impl] 在 `_classify_bidder_inner` 内,构造完 `user_msg` 之后、`llm.complete(...)` 调用之前,插入 **input shape** `logger.info` 一行:`"role_classifier input files=%d snippet_empty=%d total_prompt_chars=%d file_name_has_mojibake=%s"`(snippet_empty 在循环构造 files_block_parts 时用计数器累加;mojibake 判定用 `any(_looks_mojibake(d.file_name or "") for d in docs)`)
- [x] 1.3 [impl] 在既有 `if result.error is not None:` warning 里,保留原 format `"role_classifier LLM error kind=%s msg=%s; fallback to keywords"`(不回归);不追加新字段
- [x] 1.4 [impl] 在既有 `if parsed is None:` warning 里,追加 `raw_text_head=` 字段;消息改为 `"role_classifier LLM returned invalid JSON; fallback to keywords raw_text_head=%r"`,第二参数 `(result.text or "")[:200]`(Python 字符串切片按 code point,Unicode 安全)
- [x] 1.5 [impl] 在 `parsed` 有效分支里,写 DB roles 之前(即 `for item in parsed.get("roles", []):` 循环之前),统计 `high/low/missing` 三个计数:遍历 `parsed.get("roles", [])` 收集 `(doc_id, role, conf)` 的 valid 条目(role in VALID_ROLES,doc_id 为 int),按 conf 分组计 `high`/`low`;`missing = len(docs) - len({v[0] for v in valid})`;输出 `logger.info("role_classifier output llm_confidence_high=%d low=%d missing=%d", ...)` 一行;**不**改变后续写 DB 的控制流

## 2. L1 测试

- [x] 2.1 [L1] 新建 `backend/tests/unit/test_role_classifier_observability.py`,配置 `caplog.set_level(logging.INFO, logger="app.services.parser.llm.role_classifier")`
- [x] 2.2 [L1] case `test_input_shape_logged_with_all_fields`:mock LLM 返有效 JSON(2 个 doc 都 high);断言 caplog 捕获 input shape info,含 `files=2`、`snippet_empty=`、`total_prompt_chars=`、`file_name_has_mojibake=False`
- [x] 2.3 [L1] case `test_output_mix_logged_on_success`:mock LLM 返 high/low/漏返混合(如 3 docs, 1 high, 1 low, 1 漏返);断言 caplog 捕获 output mix info,`llm_confidence_high=1 low=1 missing=1`;总和等于文档数
- [x] 2.4 [L1] case `test_output_mix_not_logged_on_llm_error`:mock LLM 返 `LLMResult(error=LLMError(kind="timeout"))`;断言捕获 input shape info + 既有 kind warning,**不**捕获 output mix info
- [x] 2.5 [L1] case `test_invalid_json_warning_includes_raw_head`:mock LLM 返非法 JSON(如 `{"roles":[{"doc`);断言捕获 warning 含 `raw_text_head=` + 完整 raw 内容(短于 200);另一个子 case 用 300+ 字符的非法串,断言截断到 200(实施拆成 2 个独立 case,共 2 case)
- [x] 2.6 [L1] case `test_looks_mojibake_heuristic`:参数化 6 组:空串→False / 纯 ASCII `"tech.docx"`→False / 纯 UTF-8 中文 `"投标文件.docx"`→False / `"._投标文件.docx"`→False / cp850-GBK 乱码 `"._µ▒ƒΦïÅ.docx"`→True / `"abc Θöéµ║É.txt"`→True
- [x] 2.7 [L1] 跑 `pytest backend/tests/unit/test_role_classifier_observability.py -v`,实际 11 case(含参数化 6)全绿 in 0.54s

## 3. 采样脚本 + 凭证 artifacts

- [x] 3.1 [impl] 新建 `e2e/artifacts/supplier-ab-n3-observability/run_sampling.py`:不复用 run_detection.py(那个是 detect 流水线,本 change 需要的是 parse 流水线 + per-bidder snapshot),自建 login / create_project / upload_bidder / wait_parse_terminal / fetch_snapshot / delete_project 6 个函数;`run_one_round` 每轮新建 sandbox project(`n3-obs-rN-<ts>`)→ 上传 A+B → 轮询 bidder.parse_status 到 terminal(identified/identify_failed)→ 抓 snapshot → 删 project;`main` 连跑 ROUND_COUNT=2 轮,间隔 30s;产出 round1.json / round2.json / comparison.json
- [x] 3.2 [impl] 新建 `e2e/artifacts/supplier-ab-n3-observability/README.md`:本目录用途 + 如何跑(6 条前置:后端起好 / admin 登录 / admin-llm 配 key / A/B zip 存在 / logger INFO 级 / sandbox 隔离) + 4 行对比表(待填) + H1/H2/H3 解读指南 + 跨轮稳定性说明
- [x] 3.3 [manual] 2026-04-23 真 LLM 采样(ark provider / ark-code-latest)B 方案双采样完成。产出 `round1.json` / `round2.json` / `comparison.json` + 原始 `backend.log` + `sampling_run.log`。README.md 4 行对比表已填;**N3 原始症状不再复现**(2 轮均 A/B 全 high,完全一致),根因 H2a(AppleDouble `._` 文件污染 prompt)已被 `fix-mac-packed-zip-parsing` 消除。2 个 limitation:(a) uvicorn `--log-level info` 不级联 app logger,本次 info 日志未取到,结论基于 DB + warning 缺席推导;(b) run_sampling.py v1 `file_role` 字段取错已就地修复(不影响 confidence 结论)

## 4. 归档前总汇

- [x] 4.1 跑 `pytest backend/tests/unit/test_role_classifier_observability.py` 绿(11/11);跑 `pytest backend/tests/unit/ -k role_classifier` 22/22 绿(本 change 11 + 既有 11 零回归)
- [x] 4.2 跑全量 L1 + L2 —— L1 `pytest backend/tests/unit/` 1011/1011 绿 in 37.45s;L2 `pytest backend/tests/e2e/` 280 passed / 1 pre-existing fail `test_xlsx_truncates_oversized_sheet`(handoff.md 已标记,与本 change 无关),零本 change 引入的回归。L3 本 change 不触碰 UI,由 Task 3.3 的 manual 真采样凭证替代
- [x] 4.3 归档前校验:`e2e/artifacts/supplier-ab-n3-observability/` 下 `comparison.json`(1.7K)+ `round1.json`(2.7K)+ `round2.json`(2.7K)+ `README.md`(6.1K 含填完的 4 行对比表)+ `backend.log`(311K 原始 server log)+ `sampling_run.log`(1.8K)+ 修复版 `run_sampling.py`(9.1K)齐全;L1 1011/1011 绿,L2 280 passed / 1 pre-existing fail 零回归;无 UI 改动免 L3;满足归档条件
