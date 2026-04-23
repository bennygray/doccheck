# 项目 Handoff

> **跨会话/跨人接手的现场视角快照。** 计划视角见 `docs/execution-plan.md` §5。
>
> 本文档职责:记录"现在人在哪、下一步干什么、有什么没说清"。
> 最近变更历史只保留 5 条,更早历史去 `git log` 查。

---

## 1. 当前状态快照

| 项 | 值 |
|---|---|
| 当前里程碑 | **M4 完成 + V1 全量验收 + admin-llm-config + fix-mac-packed-zip-parsing** |
| 当前 change | `fix-mac-packed-zip-parsing` 归档完成。修复 macOS Archive Utility 打包 zip 的 3 个级联缺陷:**打包垃圾静默过滤**(`__MACOSX/`/`._*`/`.DS_Store`/`~$*`/`.~*`/`Thumbs.db`/`.git/` 等不产生 bid_documents 行)+ **ZIP 文件名 UTF-8 优先解码**(macOS 无 flag 场景下 `供应商A/江苏锂源...` 正确还原)+ **role 分类内容关键词兜底**(LLM 失败时两级兜底:正文首段关键词 → 文件名关键词 → "other") |
| 最新 commit | fix-mac-packed-zip-parsing 归档 |
| 工作区 | fix-mac-packed-zip-parsing 全量改动:**后端代码**:新 `services/extract/junk_filter.py`(`is_junk_entry` 纯函数 + 三类黑名单) + 改 `services/extract/engine.py`(ZIP 路径 + 7z/rar 路径双插入点 + UTF-8 启发式反向校验 + 归档行审计留痕 `(已过滤 N 个打包垃圾文件)`) + 改 `services/extract/encoding.py`(新增 `_looks_like_utf8` 严格字节模式校验 + `decode_filename` 优先 UTF-8 层) + 改 `services/parser/llm/role_keywords.py`(新增 `classify_by_keywords_on_text` + `classify_by_keywords` 改返 `str|None` 契约) + 改 `services/parser/llm/role_classifier.py`(`_apply_keyword_fallback` 改 async,两级兜底)+ 改 `services/parser/pipeline/run_pipeline.py`(`_phase_extract_content` 按 `file_type` 过滤,不再覆盖归档行 parse_error,端到端修复);**测试**:L1 新增 `test_junk_filter.py`/`test_encoding_utf8_detection.py`/`test_engine_utf8_no_flag.py`/`test_role_classifier_content_fallback.py` 共 ~80 新 case,L2 新增 `test_extract_mac_packed_zip.py`(含手工构造 UTF-8-no-flag ZIP 字节流)/`test_role_classifier_keyword_fallback.py` 共 5 新 case;L1 全量 905/905 绿;L2 受影响子集 34/34 绿;**spec sync**:`file-upload` 加 6 新 Scenario(macOS 场景、4 类垃圾过滤、审计留痕、7z/rar 路径、不误伤),`parser-pipeline` 改 2 个 Requirement 为两级兜底语义 + 补 2 个正文关键词 Scenario;**manual 凭证**:`e2e/artifacts/supplier-ab/after-fix/` JSON(bid_documents 12/14 → 4/4、identify_failed 12 → 0、file_name 乱码 Y → N、role=None 26 → 2、检测报告 section_sim=38.67 text_sim=24.51 非零信号) |

---

## 2. 本次 session 关键决策(2026-04-23,`fix-mac-packed-zip-parsing` propose+apply+archive)

### 案例触发
- 真实 A/B zip(`e2e/artifacts/supplier-ab/supplier_A.zip` 166MB / `supplier_B.zip` 9.8MB,macOS Archive Utility 打包)暴露:parser 流水线**静默降级为无意义结果**(bid_documents.role 全 None、identity_info 全 null、检测报告"全零 + 低风险无围标"误导结论)
- 用户感知:"流程跑不同/卡住了" — 实则流水线跑完但结果全 0

### propose 阶段已敲定(产品/范围级决策)
- **A/B/C 选项分三层**:A 最小(只修 macOS 那批)、B 完整黑名单(+Windows/Office/VCS,**推荐选中**)、C 白名单严打(被否决:扩展名白名单过不掉 `~$x.docx` 这类恰好是 .docx 的临时文件)
- **区分"垃圾丢弃" vs "不支持但告知"**:打包垃圾 → 静默丢弃不产 bid_documents 行;非业务扩展名 → 保留 skipped 反馈用户
- **identity_info 不做规则兜底**:保持 spec 原意("避免精度差导致污染"),follow-up 由 UI/报告侧显示"识别信息缺失"文案

### apply 现场决策
- **保留 engine.py 既有 GBK 启发式 + 后置 UTF-8 校验**(而非整段删改):零回归路径,Windows GBK 包不受影响
- **`classify_by_keywords` 契约变更** None on miss(原返 "other"):便于上层两级兜底区分"命中 other" vs "未命中";同步更新唯一 production 调用点 + 2 个测试文件
- **fixture scope-safe 清理**:共享 dev DB 里有 project 226 的老数据,既有 `test_parser_llm_role_classifier.py` 的 `DELETE WHERE id>0` 会和 FK 冲突;改为按 `User.username` 前缀过滤只删本测试的 seed
- **端到端修 `_phase_extract_content`**(范围外但必要):真实 A/B 验收暴露 pipeline 把 .zip 归档行也扔给 `extract_content`,标成"未知文件类型 .zip" 覆盖我写入的 "已过滤 N 个" 审计文本;加一行 `file_type.in_([".docx",".xlsx"])` 过滤 + 回归测试
- **L2 fixture 手工构造 UTF-8-no-flag ZIP**:Python stdlib `zipfile` 对非 ASCII 文件名会强制置位 bit 11,无法原生模拟 macOS 无 flag 场景;手写本地文件头+中心目录+EOCD 精确控制 flag
- **manual 凭证用 JSON 代截图**:CLI 环境无 GUI,`verify.py` 调真 LLM 跑完整流程把 `bidders_before_detect / documents_A / documents_B / analysis_status / report` JSON 落盘到 `e2e/artifacts/supplier-ab/after-fix/`

### 文档联动
- **`openspec/specs/file-upload/spec.md`** 改 "压缩包安全解压" Requirement,+6 新 Scenario
- **`openspec/specs/parser-pipeline/spec.md`** 改 "LLM 角色分类与身份信息提取" + "角色关键词兜底规则" 两个 Requirement
- **`docs/handoff.md`** 即本次更新

### 发现但 **不在本次 change 范围** 的遗留问题(10 条)
参见 archive 目录 `openspec/changes/archive/2026-04-23-fix-mac-packed-zip-parsing/design.md` §5"Open Questions" 上下文。总览 + 优先级:
- **F2 高**:judge LLM 全零/全 skipped 时仍给"无围标"误导结论 — 应返"证据不足"
- **F1 中**:ProcessPool 崩溃兜底(per-task 进程隔离);A/B 案例靠垃圾过滤"绕过"但根因没修
- **F3 中**:identity_info NULL 时 UI/报告侧文案降级
- **N3 中**:大文档(如 161MB docx)下 LLM role_classifier 精度退化(A 全走兜底 low,B 全 high)— 需先开日志调查
- **N5 中**:共享 dev DB 污染导致 `pytest tests/e2e/` 全量跑不动 — testdb 容器化
- **N7 低-中**:LLM provider `.complete()` 没统一 `asyncio.wait_for`
- **N2 低-中**:`ROLE_KEYWORDS` 补 "价格标"/"资信标"(A 的"价格标/资信标"因此没命中 pricing/qualification)
- **N4 低**:analysis completion 与 report 生成时序不对齐(需加 `report_ready` 字段)
- **N6 低**:`make_gbk_zip` fixture 实际产出不是声称的东西(flag 被强制置位)— 重写
- **N8 低**:归档行(.zip)在 UI 的语义模糊 — 按 file_type 折叠

---

## 2.bak_admin-llm-config 上一 session 关键决策(2026-04-20,`admin-llm-config` propose+apply+archive)

### propose 阶段已敲定(5 产品级决策)

- **Q1 B dashscope + openai + custom**:白名单 3 种,custom = OpenAI 兼容端点
- **Q2 B 末 4 位保留**:`sk-****abc1`;短于 8 位固定 `sk-****` 占位
- **Q3 B 做测试连接按钮**:发 `"ping"` + max_tokens=1,最省 token
- **Q4 B 三层优先级**:DB > env > 代码默认;保持旧部署兼容
- **Q5 B 指纹哈希 cache + PUT 失效**:(provider, key, model, base, timeout) 作 key,PUT 后清空

### apply 现场决策

- **audit_log 暂不写 admin-llm 更新**:`AuditLog.project_id` 非空,系统级配置不挂项目;Follow-up 改 project_id nullable 或新建 SystemAuditLog
- **factory `get_llm_provider()` 保持同步签名 + env 路径**:11 个 Agent / judge / pipeline 现有调用零改动;新增 `get_llm_provider_db(session)` 异步路径供后续逐步切换
- **`@lru_cache` 换成 dict 指纹缓存**:上限 3,FIFO 淘汰,防病态输入撑爆
- **Tester `max_tokens=1` + timeout 强制 ≤10s**:防 UI 卡死
- **前端 api_key 空白不传**:占位符显示脱敏值,空白提交 → 后端保持旧值

### 文档联动

- **`openspec/specs/admin-llm/spec.md`** 新建:6 Req / 14 Scenario
- **`e2e/artifacts/admin-llm-2026-04-20/README.md`** L3 手工凭证
- **`docs/handoff.md`** 即本次更新

---

## 2.bak_C17 上一 session 关键决策(2026-04-16,C17 `admin-users` propose+apply)

- Q1 A 仅全局级 SystemConfig / Q2 A 覆盖写 + 恢复默认 / Q3 A admin 手动创建 / Q4 A §8 最小集
- L3 手工凭证:`e2e/artifacts/c17-2026-04-16/README.md`

---

## 2.bak_C15 上上一 session 关键决策(2026-04-16,C15 `report-export` propose+apply)

### propose 阶段已敲定(4 产品级决策)

- **Q1 C Word 模板两者结合**:内置默认 + 用户上传可覆盖 + 上传坏掉回退内置
- **Q2 D 复核粒度组合**:整报告级(必须)+ 维度级(可选)
- **Q3 A 独立 `audit_log` 表全字段**
- **Q4 D 异步 + 预览链接 + 三兜底**

### apply 阶段就地敲定(重要现场决策 B2)

- **design D4 改 B2**:原 design 假设复用 `async_tasks`,apply 发现侵入大;就地改独立 `export_jobs` 表(14 字段)

---

## 2.bak_C14 上一 session 关键决策(2026-04-16,C14 propose+apply+archive)

- Q1 B 预聚合结构化摘要 / Q2 A 公式兜底 / Q3 B 可升不可降+铁证 85 守护 / Q4 C 不做跨项目共现 / Q5 C 降级模板+前缀哨兵
- apply:AgentRunResult 字段名修正 / e2e autouse fixture / fallback 前缀约束 / summarize 铁证无条件入 top_k

---

## 2.bak_C13 上一 session 关键决策(2026-04-15,C13 propose+apply+archive)

- Q1 合并 / Q2 (A) L-5 铁证 / Q3 (C) MD5+pHash 双路 / Q4 (C) L-8 全 LLM / Q5 零新增依赖
- apply:不扩 AgentRunResult 改走 OA evidence 顶层 / DocumentText 行级 SQL / imagehash int64 cast

---

## 3. 待确认 / 阻塞

- 无硬阻塞,**M4 完成(3/3),全部 17 个 change 已归档**
- **Follow-up(C16)**:字符级 diff / price evidence 对齐 / 对比页面导出
- **Follow-up(C17)**:元数据白名单已通过 admin 规则配置可编辑（✅ 已解决）；按维度分 Tab 的完整配置 UI（第二期）
- **Follow-up(C15)**:用户模板上传 UI / PDF 导出 / 批量导出 / audit 过滤器 / 导出历史页
- **Follow-up(C14)**:跨项目历史共现 / DIMENSION_WEIGHTS 实战调参 / L-9 prompt N-shot 精调
- **Follow-up(持续)**:Docker kernel-lock 未解(C3~C17 L3 全延续手工凭证)
- **Follow-up(持续)**:生产部署前 env 覆盖全清单
- **Follow-up(产品决策搁置,2026-04-22)**:投标包内若报价单为 `.doc/.docx` 而非 `.xlsx`,当前链路**静默 skip**(无报错),导致 price_consistency 维度漏检
  - 现状代码位置:`run_pipeline.py:_find_pricing_xlsx` 硬过滤 `.xlsx` / `fill_price.py` 仅走 `extract_xlsx` / `price_consistency.py` preflight 找不到时 skip
  - 已评估两条路径并**搁置**:
    - 最小止血(1 天):改为显式 failed + UI 提示"报价单非 xlsx 格式,需人工"
    - 完整方案(6-8 天):抽象 tabular region + docx 表抽取 + LLM 兜底 C(详见此 session 讨论记录)
  - 触发重启条件:业务侧反馈 docx 报价单出现频率显著上升,或出现因此漏检的围标 case

---

## 4. 下次开工建议

**一句话交接**:
> **M4 完成,全部 17 个 change 已归档。** C15 报告导出 + C16 对比视图 + C17 用户管理/规则配置 = M4 可交付。系统具备完整的上传→解析→检测→报告→导出→对比→管理能力。下一步：M4 演示级交付凭证 + follow-up 规划（第二期 backlog 整理）。

**可直接粘贴给 AI 作为新会话起点**:
```
继续 documentcheck 项目。M4 已完成(3/3),C17 admin-users 已 archive + push。
全部 17 个 change（C1~C17）已归档,系统达到可交付状态。
下一步:
  1. M4 演示级交付凭证(execution-plan §4 要求:Word 报告示例 + 管理操作截图)
  2. follow-up backlog 整理(C14~C17 累积的 follow-up 项)
  3. 第二期规划(US-9.2 按维度分 Tab / US-10 LLM 配置 / 跨项目历史共现 等)
请先读 docs/handoff.md 和 docs/execution-plan.md §4~§6 确认现状。
也检查 memory 和 claude.md。
```

---

## 5. 最近变更历史(仅保留最近 5 条)

| 日期 | 变更 |
|---|---|
| 2026-04-16 | **DEF-OA `fix-dimension-review-oa` 归档**:judge.py 补写 7 pair 维度 OA 聚合行;error_consistency/image_reuse early-return 补 OA;维度级复核 API 全 11 维度可用;L1 801 + L2 250 全绿 |
| 2026-04-16 | **V1 全量验收测试**:`docs/v1-acceptance-test-report.md` 55/66 通过(96.5% 可执行通过率);2 失败(AT-7.7 LLM 降级 UI / AT-9.2 维度复核);9 阻塞(fixture 不足) |
| 2026-04-16 | **DEF-007 `fix-l3-acceptance-bugs` 归档**:BUG-2 TEXT_SIM_MIN_DOC_CHARS 500→300;BUG-3 get_current_user 支持 query param token + ExportButton/useDetectProgress SSE URL 追加 token;WARN-1 AdminRulesPage input null→"";L3 11/11 全绿 |
| 2026-04-16 | **DEF-006 `fix-silent-project-transition-failure` 归档**:run_pipeline 6 处 try_transition_project_ready 加异常保护;trigger.py task 引用持有+done callback 异常日志;4 新增 L1 用例 |
| 2026-04-23 | **`fix-mac-packed-zip-parsing` 归档**:macOS 打包 zip 的 3 个级联缺陷(打包垃圾 + UTF-8 无 flag 文件名 + role 分类链路断裂)一次修 + bonus 修 phase1 覆盖归档行 parse_error;真 A/B zip 验收 bid_documents 12/14→4/4、identify_failed 12→0、role=None 26→2、检测报告非零信号 |
