## Context

`backend/app/services/extract/` 当前解压策略:

- `engine.py` ZIP 分支(L420-590):按 entry 迭代,解码文件名(L437-460 的 GBK 启发式)→ 路径安全检查 → 写盘 → 建 `bid_documents` 行
- `engine.py` 7z/rar 分支(通过 `_walk_extracted_dir`, L705+):一次性 extractall 到临时目录,再扫盘建行
- `encoding.py`(51 行):`decode_filename(raw_bytes, is_utf8_flagged)` — UTF-8 flag 优先 → GBK 默认尝试 → chardet 兜底(阈值 0.7)→ latin1 fallback

`backend/app/services/parser/role_classifier.py`:

- 主路径(`classify_bidder`, L57-169):对所有 `parse_status=identified` 的文档,取 `file_name` + 首段 ≤500 字构建 LLM prompt → 返 `{roles:[], identity_info:{}}` → 写 `doc.file_role` + `bidder.identity_info`
- 降级(`_apply_keyword_fallback`, L172-176):LLM 失败时对每个 doc 调 `classify_by_keywords(doc.file_name)` → `role_keywords.py` 做 substring 匹配 → 失败返 `"other"`

**本次 A/B 案例暴露的事实链**(见 `e2e/artifacts/supplier-ab/inspect_docs.log`):

1. macOS Archive Utility 打包时把中文文件名存为 UTF-8 字节但不置 ZIP bit 11(spec 允许,但 Python zipfile 默认按 cp437 解码)
2. 当前 `encode("cp437").decode("gbk")` 启发式对"UTF-8 字节被 cp437 解码"的字符串会产出一串含假 CJK 码点的垃圾(`Σ╛¢σ║öσòåA`),被"含 CJK 字"判定误认可
3. 乱码文件名传给 LLM prompt → 分类无线索;传给关键词兜底 → 零命中
4. 同包内的 `__MACOSX/._xxx.docx` AppleDouble stub(176 字节)被当 `.docx` 送进 python-docx → `Package not found` 报错;每个真 docx 都有 1:1 的 `._` 影子,造成 5~7 个 identify_failed 占位行污染 `bid_documents`

## Goals / Non-Goals

**Goals:**
- macOS Archive Utility 打包的 zip 能像 Windows 7-Zip 打包一样解析:`bid_documents` 只含真实业务 docx,文件名中文正确,role 尽可能分配非空
- 打包垃圾过滤规则可扩展(下次遇到新型号打包工具新增 pattern 即可,不改流程)
- 修复对现有 Windows GBK-packed zip 零影响(不引入回归)
- 降级链路多一层防线:LLM 失败 + 文件名异常时仍能靠正文关键词分配 role

**Non-Goals:**
- 不修 ProcessPool 崩溃隔离(section/text_similarity 被坏 docx 拉崩整池是另一层问题,另开 change)
- 不修 judge LLM 的"全零 → 低风险"误导性结论(那是 judge 层逻辑,另开 change)
- 不做 identity_info 的正则兜底抽取(spec 明确不做,避免脏数据传染;另开 UI 降级文案 change)
- 不追溯清理历史 `bid_documents` 里的打包垃圾占位行
- 不扩展非业务扩展名处理(`.rtf`、空文件等继续走当前 skipped 路径)

## Decisions

### D1:用"字节模式严格校验"判 UTF-8,不用 chardet

UTF-8 的 lead/trail byte 有明确规则(0xC0-0xDF + 1×0x80-0xBF / 0xE0-0xEF + 2× / 0xF0-0xF7 + 3×),严格校验成本低、零歧义。

**为什么不用 chardet?**  对 8 字节左右的短文件名置信度不稳,之前阈值 0.7 经常 miss;降阈值又会误伤其他编码。

**为什么不用"双向评分"方案?**  启发式权重调参维护成本高;UTF-8 合法性是二分的(合规就是合规),不需要评分。

### D2:UTF-8 检查 > GBK 默认,顺序固定

`decode_filename` 决策顺序调整为:
1. UTF-8 flag 置位 → UTF-8
2. **(新)** raw bytes 是合法 UTF-8 字节序列 → UTF-8
3. 尝试 GBK(现有)
4. chardet 兜底(现有)
5. latin1(现有)

**为什么 UTF-8 检查在 GBK 前?**  GBK 字节序列极难凑成合法 UTF-8 多字节序列(需要恰好落在 0x80-0xBF trail 区间,真实中文文件名中命中概率接近 0)。反之 UTF-8 用 GBK 解码必定得到"假 CJK"垃圾(每 3 个 UTF-8 字节 → 1.5 个 GBK 字符,码点随机落在 CJK 区间),所以"GBK 能 decode"完全不能证明它就是 GBK。

**回归风险**: 纯 ASCII 文件名两种顺序都不受影响;混合文件名(中文 + ASCII)的 UTF-8 字节流总是合法 UTF-8,GBK 也总能 decode,但 UTF-8 解码的结果语义正确。

### D3:ZIP engine.py 的 cp437-GBK 启发式保留,但输出做二次校验

`engine.py` L446-457 的启发式在历史上对 Windows GBK 包很有效(info.filename 是 cp437-解码的 GBK 字节的乱码 → encode cp437 → decode GBK → 拿回真 GBK 字符串)。

**决策**:保留这段启发式(对 Windows GBK 真实场景有效),但在输出 `gbk_view` 后**加一步反向验证**:尝试把 `gbk_view` 按 GBK 编码回字节,再按 UTF-8 解码,**能成功且得到的 UTF-8 字符串是合法的(通过 D1 的字节模式检查)就优先用 UTF-8 版本**。即:

```
启发式产出 gbk_view
  → utf8_candidate = gbk_view.encode("gbk").decode("utf-8")   # 能成功说明原字节是 UTF-8
  → 若 utf8_candidate 通过 UTF-8 字节模式合法性,并且它的字节等于原 cp437_bytes
  → 用 utf8_candidate(说明原字节是 UTF-8 被 cp437 误解)
  → 否则用 gbk_view(原 GBK 场景)
```

**为什么不直接移除启发式,全部走 `decode_filename`?** 那样 Windows GBK 真实 zip(已大量存在)会走到 chardet 兜底,短文件名会失效回归。保留启发式 + 后置校验是零回归路径。

### D4:junk_filter 单独模块,纯函数

`backend/app/services/extract/junk_filter.py` 只暴露 `is_junk_entry(relative_path: str) -> bool`,无 IO、无状态,好单测。

**规则三类合一**:
- 目录名集合(大小写敏感,macOS/Unix 约定都是固定大小写)
- basename 全等集合(大小写**无关**,Windows 文件系统不区分)
- basename 前缀(大小写敏感,`._` / `~$` / `.~` 都是 ASCII 约定)

**为什么不用配置化?**  黑名单是稳定事实(几十年前的 macOS/Windows/Office 惯例),不值得做 SystemConfig 动态配置。下次新增 pattern 改代码 + 一条单测即可。

### D5:过滤在 ZIP entry 迭代 + 7z/rar `_walk_extracted_dir` 两处插入

- **ZIP 路径**:在 `decoded.endswith("/")` 判断后、`check_safe_entry` 前(engine.py L461 附近),命中 `is_junk_entry(decoded)` 则 `continue`,不落盘不建行
- **7z/rar 路径**:在 `_walk_extracted_dir` 循环顶(engine.py L716 附近,`rglob("*")` 返回后),命中则 `path.unlink()` 删落盘垃圾 + `continue`

**为什么不统一在 _walk_extracted_dir 里?** ZIP 路径是流式:垃圾 entry 连写盘都不该发生,早过滤省 IO。7z/rar 是先 extractall 再扫,只能后过滤。

**审计留痕**:在 `counters` 里加 `junk_skipped` 计数,`extract_archive` 返回时写进归档行的 `parse_error` / summary,格式 `(已过滤 N 个打包垃圾文件)`,让运维能查到。

### D6:role 内容兜底在"文件名关键词"之前,不改 LLM 主路径

`role_classifier.py::_apply_keyword_fallback` 当前直接对每个 doc 调 `classify_by_keywords(doc.file_name)`。

**决策**:改为"先试首段正文关键词 → 没命中再试文件名关键词"。

```
_apply_keyword_fallback(docs, session):
  for doc in docs:
    if doc.parse_status == "identified":
      text = await _get_first_paragraph(session, doc.id, max_chars=1000)
      role = classify_by_keywords_on_text(text)
      if role != "other":
        doc.file_role = role; doc.role_confidence = "low"
        continue
    doc.file_role = classify_by_keywords(doc.file_name) or "other"
    doc.role_confidence = "low"
```

**为什么不改 LLM 主路径?** LLM 能拿到正文片段(500 字 snippet)已经足够,问题在乱码文件名干扰它;本次编码修复后 LLM 主路径自然恢复。兜底层才是需要 defense-in-depth 的地方。

**为什么内容关键词在文件名关键词之前?** 当 LLM 失败时,大部分场景是因为文件名太乱(乱码/缩写/数字编号)—— 这些场景正文更可靠。对"文件名清晰但正文不相关"的场景极少见(投标文件首段基本都有标题或关键词)。

### D7:identity_info 本次不做兜底

LLM 失败时 `bidder.identity_info` 保持 NULL。

**理由**:identity_info 是四字段结构(company_name/legal_representative/reg_number 等),正则提取假阳性代价很高("见法人代表签字页"扫到就错归一个人);spec 本就注释说明"不做规则兜底"。正确解法是让 `error_consistency` agent 在 NULL 时优雅降级显示"识别信息缺失,无法判定",那是另一个 change。

## Risks / Trade-offs

- **[R1] Windows GBK 真实 zip 被 D1 的 UTF-8 字节校验误接受** → 缓解:GBK 字节凑成合法 UTF-8 多字节序列的概率极低(需要 lead byte + trail byte 两两精确对齐),L1 单测覆盖 `供应商A` GBK 字节 → False 的负例断言;真实回归可在 manual 阶段用历史 Windows 包验证
- **[R2] junk_filter 误伤用户真实命名的文件** → 可能场景:用户真的把业务文件命名为 `~$XXX.docx` 或 `._XXX`(极罕见);缓解:这些 pattern 在业务语境里都是系统约定,L1 单测覆盖 `my._file.docx`(中间 `._` 不算)等边界;真发生可由用户反馈加白名单豁免
- **[R3] 内容关键词兜底性能影响** → 额外 SELECT `document_texts`(按 `bid_document_id` + `paragraph_index` 升序 LIMIT 1,已有索引);每个 bidder 仅在 LLM 失败分支才触发,正常路径零开销
- **[R4] 过滤规则落后于新打包工具** → 缓解:规则是纯函数,加 pattern 改一行 + 加单测,成本极低
- **[R5] 历史数据里的打包垃圾占位行** → 本次不做回溯清理,这些行存在但只是 UI 噪音,不影响检测;如需清理另开脚本 change(优先级低)

## Migration Plan

本次无 DB migration,纯代码改动:

1. L1 全绿 → L2 全绿(本地 `pytest`)
2. manual:用 `e2e/artifacts/supplier-ab/supplier_A.zip` + `supplier_B.zip` 在本地 backend 重跑全流程,截图凭证落 `e2e/artifacts/supplier-ab/after-fix/`
3. archive + commit(按 CLAUDE.md 的 archive-change 自动 commit 约定)
4. 回滚:git revert 此 change commit;不涉及 DB schema,无迁移回滚

## Open Questions

- **Q1**:归档行 summary 里"已过滤 N 个打包垃圾文件"的提示字符串是否需要前端在 UI 上突出显示?—— 本次暂不改前端,summary 只作为运维 debug 线索
- **Q2**:D3 的"启发式产出后反向校验 UTF-8"判断是否需要额外引入 identity 检查(`utf8_candidate.encode("utf-8") == cp437_bytes`)来保证零假阳性?—— 实现时加,L1 单测覆盖
