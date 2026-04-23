## 1. 打包垃圾过滤模块

- [x] 1.1 [impl] 新建 `backend/app/services/extract/junk_filter.py`,实现 `is_junk_entry(relative_path: str) -> bool` 纯函数,包含三类常量集合:`_JUNK_DIR_COMPONENTS`(目录名精确匹配,大小写敏感)、`_JUNK_BASENAMES_CI`(basename 全等,大小写无关)、`_JUNK_BASENAME_PREFIXES`(basename 前缀,大小写敏感);规则按 design.md D4 节展开
- [x] 1.2 [impl] 在 `backend/app/services/extract/engine.py` 的 ZIP 迭代分支(约 L461,`decoded.endswith("/")` 判断之后、`check_safe_entry` 之前)插入 `is_junk_entry(decoded)` 命中即 `continue`,并在 `counters` 中累加 `junk_skipped` 计数
- [x] 1.3 [impl] 在 `backend/app/services/extract/engine.py::_walk_extracted_dir`(约 L716)循环顶插入 `is_junk_entry(relative)` 命中时 `path.unlink()` 删落盘文件 + `counters["junk_skipped"] += 1` + `continue`
- [x] 1.4 [impl] 在 `extract_archive` 返回前把 `counters["junk_skipped"]` 写入归档行的 `parse_error` 或 summary 字段,格式 `(已过滤 N 个打包垃圾文件)`(N>0 时才写)
- [x] 1.5 [L1] 新建 `backend/tests/unit/test_junk_filter.py`,覆盖 design.md Risks 表和 specs 中列举的所有正例/反例/边界场景(`__MACOSX/`、`._*`、`.DS_Store`、`~$*`、`.~*`、`Thumbs.db` 大小写、`.git/`、`node_modules/` 等目录前缀;负例:`my~dollar.docx`、`my._file.docx`、`.gitignore`、`normal.docx`;边界:空串、`foo/`、Windows 反斜杠路径) — 54 cases green

## 2. ZIP 文件名 UTF-8 优先解码

- [x] 2.1 [impl] 在 `backend/app/services/extract/encoding.py` 新增内部函数 `_looks_like_utf8(raw_bytes: bytes) -> bool`,按 design.md D1 的字节模式规则严格校验(纯 ASCII → True;含高位字节时校验 0xC0-0xDF + 1×0x80-0xBF / 0xE0-0xEF + 2× / 0xF0-0xF7 + 3× 的多字节结构,空字节 / 截断多字节序列 / 孤立 trail byte 一律 False)
- [x] 2.2 [impl] 修改 `decode_filename(raw_bytes, *, is_utf8_flagged)`:在现有"UTF-8 flag → GBK 默认 → chardet → latin1"链路中,在 UTF-8 flag 判断**之后**、GBK 默认尝试**之前**,插入"`_looks_like_utf8(raw_bytes)` 通过 → `raw_bytes.decode('utf-8')`"一层
- [x] 2.3 [impl] 修改 `backend/app/services/extract/engine.py` ZIP 启发式(约 L446-457):启发式产出 `gbk_view` 后,计算 `utf8_candidate = cp437_bytes.decode('utf-8', errors='strict')`;若能成功且 `_looks_like_utf8(cp437_bytes)` 通过,则优先使用 `utf8_candidate`(说明原字节是 UTF-8 被 cp437 误解);否则保持现有 GBK 行为
- [x] 2.4 [L1] 新建 `backend/tests/unit/test_encoding_utf8_detection.py`,覆盖 `_looks_like_utf8` 的纯 ASCII / `供应商A` UTF-8 字节 / `供应商A` GBK 字节(应为 False,避免误判)/ 日文 `テスト` UTF-8 / 空字节 / 截断 UTF-8 序列;端到端覆盖 `decode_filename` 对以上场景的输出 — 17 cases green
- [x] 2.5 [L1] 新增 `backend/tests/unit/test_engine_utf8_no_flag.py`:手工构造 ZIP 字节流(filename 用原始 UTF-8 字节,flag bit 11=0),模拟 macOS Archive Utility 行为,验证 ZIP 启发式现在正确解出 UTF-8 中文,同时 GBK 真实场景零回归 — 3 cases green

## 3. role 分类内容关键词兜底

- [x] 3.1 [impl] 在 `backend/app/services/parser/llm/role_keywords.py` 新增 `classify_by_keywords_on_text(text: str) -> str | None` 函数,复用 `ROLE_KEYWORDS` 做子串包含匹配(不区分大小写),按字典声明顺序首次命中即返回,全未命中返回 `None`;同时调整 `classify_by_keywords(file_name)` 返回值,使其未命中时返回 `None`(而非 `"other"`),以便上层区分"命中 other" vs "未命中"
- [x] 3.2 [impl] 修改 `backend/app/services/parser/role_classifier.py::_apply_keyword_fallback` 为两级兜底:对 `parse_status='identified'` 的文档先读 `document_texts` 首段(按 `paragraph_index` 升序、`location='body'` 的最早一条,截 ≤1000 字,若无则跳过此层)调 `classify_by_keywords_on_text`,命中即赋 role + `confidence='low'`;未命中(或 parse_status != identified)再落到 `classify_by_keywords(doc.file_name)`;仍未命中 → `role='other', confidence='low'`;函数签名从 sync 改为 async(三处调用点同步更新)
- [x] 3.3 [impl] 校对所有调 `classify_by_keywords(...)` 的现有旁路 — grep 确认只有 `role_classifier._apply_keyword_fallback:175` 一个 production 调用点,已在 3.2 中更新;同时同步更新 `tests/unit/test_parser_llm_role_keywords.py` 与 `test_parser_llm_role_classifier.py` 的 fixture(后者 fixture 遇 `DELETE id>0` 与共享 DB 老数据 FK 冲突,改为 scope-safe 按 user prefix 清理)
- [x] 3.4 [L1] 新建 `backend/tests/unit/test_role_classifier_content_fallback.py`,覆盖:文件名乱码 + 正文含"投标报价一览表" → `role=pricing`;文件名乱码 + 正文含"技术方案" → `role=technical`;文件名乱码 + 正文无关键词 → `role=other`;文件名正常("投标报价.xlsx")+ 正文空 → 走文件名路径 `role=pricing`;文档 parse_status != identified → 跳过正文兜底直接走文件名 — 6 cases green

## 4. L2 集成测试

- [x] 4.1 [L2] 新建 `backend/tests/e2e/test_extract_mac_packed_zip.py`:手工构造 ZIP 字节流(filename 用 UTF-8 字节、flag bit 11=0,Python stdlib `zipfile` 对非 ASCII 文件名会强制置位 flag 所以必须手写头+中心目录+EOCD)模拟 macOS 打包。包含 1 份真 docx + 7 个垃圾 entry(`__MACOSX/._x` × 2、`.DS_Store`、`~$x.docx`、`.~x.docx`、`Thumbs.db`、AppleDouble DS);断言:(a)`bid_documents` 只有 1 行真 docx;(b)`file_name` 为正确中文(江苏锂源一期-技术标-...);(c)归档行 `parse_error` 含"已过滤 6 个";(d)落盘目录里零 `__MACOSX`/`._`/`.DS_Store`/`Thumbs.db`/`~$`/`.~` 文件。Role 分类在 L1 + 4.2 覆盖,本 L2 聚焦 extract 层;**外加**:真实 A/B 跑验收暴露 `run_pipeline._phase_extract_content` 没按 `file_type` 过滤会把 .zip 归档行当文档跑进 `extract_content` → 标成 "未知文件类型 .zip" **覆盖** 我写入的 "已过滤 N 个" 审计留痕;加了一行 `file_type.in_([".docx", ".xlsx"])` 过滤 + 回归测试 `test_pipeline_phase1_skips_archive_rows` — 3 cases green
- [x] 4.2 [L2] 新建 `backend/tests/e2e/test_role_classifier_keyword_fallback.py`:走 `run_pipeline` 整条链路(phase1 extract_content 用 monkeypatch 置 no-op 绕过,phase2 LLM mock 成 timeout 错),验证正文关键词兜底在流水线集成点生效。断言文件名乱码 + 正文"技术方案" → role=technical low;文件名"投标报价.xlsx" + 正文无关键词 → 走文件名兜底 pricing low — 2 cases green

## 5. 人工验证凭证(manual)

- [x] 5.1 [manual] 重启 backend,用 `e2e/artifacts/supplier-ab/supplier_A.zip` 和 `supplier_B.zip` 真实 zip 新建项目 → 上传 → parse → 检测。凭证以 JSON 形式(非截图,终端环境)落盘到 `e2e/artifacts/supplier-ab/after-fix/`:
  - `bidders_before_detect.json`:parse 完 bidder+documents 快照
  - `documents_A.json` / `documents_B.json`:每 bidder 的 bid_documents 详表 — **4 行 = 1 归档 + 3 真 docx**,中文文件名完整正确(`江苏锂源一期空压机投标文件-技术标正本-萨震-2025.12.29.docx` 等)
  - `analysis_status.json`:11 个 agent 最终状态(8 succeeded + 3 skipped,**0 failed**;`section_similarity=49994ms`、`text_similarity=65139ms`,之前会 `BrokenProcessPool` 崩溃的 agent 都跑完了)
  - `report.json`:检测报告(`total_score=3.68 risk=low`,section_similarity=38.67 / text_similarity=24.51 都是非零信号;修复前是"全零 + 低风险无围标"误导结论)
  - **修复前 vs 后对比表**(verify.py 自动打印):bid_documents(A) 12→4;(B) 14→4;identify_failed 12→0;file_name 乱码 Y→N;role=None 26→2(仅归档行)
- [x] 5.2 [manual] `docs/handoff.md` 更新随 archive 阶段的自动 commit 一起写入(CLAUDE.md `archive 自动 commit` 约定)

## 6. 总汇

- [x] 6.1 跑 [L1][L2] 全部测试,全绿(本次 change 无 L3 任务):
  - **L1 全量**:`uv run pytest tests/unit` → **905 passed**(包含 17.42s 运行的全量,含新增 `test_junk_filter.py`/`test_encoding_utf8_detection.py`/`test_engine_utf8_no_flag.py`/`test_role_classifier_content_fallback.py` 共 +80 左右新 case,既有 `test_parser_llm_role_keywords.py`/`test_parser_llm_role_classifier.py` 因契约变更同步更新)
  - **L2 受影响子集**:9(extract_api) + 2(extract_mac_packed_zip) + 2(role_classifier_keyword_fallback) + 21(upload+bidders+decrypt) = **34 passed**
  - **回归笔记**:全量 `tests/e2e` 在本地 dev 共享 DB 上因老数据锁(project 226 agent_tasks 等)会挂住 `DELETE FROM system_configs` 类清理 SQL,这是 pre-existing 问题,不是本次 change 引入;受影响的 extract/parser/upload 子集单独跑全绿
