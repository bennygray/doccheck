# L3 minimum-set — detect-tender-baseline §3.7

- **Change**: `detect-tender-baseline` (M5)
- **Scope**: §3 text_similarity 接入 — 段级 baseline 跳过 ironclad
- **Commit hash 验证版本**: `f38aef1`
- **测试日期**: 2026-04-30
- **测试性质**: 真后端 / 真 LLM(火山引擎 Ark)/ 真客户演示 zip,**非 mock**
- **运行人**: Claude Code (session)
- **凭证目录**: `e2e/artifacts/detect-tender-baseline-2026-04-30/text-sim-minimum-set/`

## TL;DR

**结论**:§3 代码在真后端 + 真 LLM 路径**功能正确**。tender 上传 + 解析 + 段级 hash 写入流水线**全链路工作**;text_similarity detector 调 baseline_resolver 拿段级 hash 集合 + 段级 baseline_matched / baseline_source 段级字段写 evidence_json **全部生效**。

**意外发现**:真客户演示 zip(vendor-A/B/C)的应标方文档**高度 customize 模板内容**,经 sha256 段级 hash 比对 vendor B-C 全 40 个 samples **0 段命中 tender 段集**。该现象不是 §3 的 bug,而是符合预期的"应标方填好的投标文件 ≠ 招标方下发模板"的真实状态。**该 zip 因此无法直接演示"tender 命中段被剔除 ironclad"的正向效果**;该正向效果由 [test_text_sim_baseline_e2e.py](backend/tests/e2e/test_text_sim_baseline_e2e.py) 5 个 L2 case 全覆盖(seed 投标方段=tender 段,直接观察 is_ironclad 翻 False)。

| 指标 | 期望 | 实际 | 通过 |
|---|---|---|---|
| Tender 解析 | parse_status=extracted + segment_hashes ≥ 1 | extracted, **210 段 hash + 10 BOQ hash** | ✓ |
| baseline_resolver 调用 | text_similarity.run() 调 get_excluded_segment_hashes_with_source 不抛 | 不抛(evidence.baseline_source 字段被写入) | ✓ |
| evidence_json schema 扩展 | samples[i] 含 baseline_matched + baseline_source 段级 + 顶级 baseline_source + warnings | 全 40 sample 含 4 字段 + 顶级字段就位 | ✓ |
| 段级 baseline 命中 | ≥ 1 段命中 tender(vendor 保留模板原文时) | **0 段命中**(vendor 高度 customize) | 数据问题非 §3 |
| baseline_source 取值 | 'tender' / 'consensus' / 'none' 之一 | **'none'**(0 段命中) | ✓ |
| L3 立场:无 baseline 仍升 ironclad | 7 plag + 2 exact_match → True | **is_ironclad=True**(7 plag + 2 exact_match) | ✓ |
| § 3 改动 0 回归 | 老路径行为不变 | 单元 1332 + e2e 309 全绿 | ✓ |

---

## 1. 测试场景与数据

### 项目
- **id**: 3709
- **name**: `L3-min-set-tender-baseline-text-sim`
- **owner**: admin
- **created_at**: 2026-04-30T09:06:47Z

### 投标方
| bidder_id | name | source archive | parse_status | DocumentText 数 / 含 segment_hash |
|---|---|---|---|---|
| 4174 | vendor-A | `C:\Users\7way\Downloads\repro_test\vendor-A.zip` (86 MB) | partial(PDFs skipped, docx/xlsx 全 identified) | 3507 / 3454 |
| 4175 | vendor-B | `vendor-B.zip` (76 MB) | partial | 8535 / 8495 |
| 4176 | vendor-C | `vendor-C.zip` (186 MB) | partial | 5162 / 5103 |

### Tender(招标方下发模板)
- **file_name**: `模板.zip`
- **md5**: `(见 tender_document.json)`
- **parse_status**: extracted
- **segment_hashes**: 210
- **boq_baseline_hashes**: 10
- **来源 zip**: `C:\Users\7way\Desktop\测试\模板.zip`(142 KB,内含 4 份 docx/xlsx 模板)

### Tender 上传路径(已知 bug 绕过)
- 上传 API `POST /api/projects/3709/tender/` **被 [validator._validate_magic](backend/app/services/upload/validator.py:50) libmagic 误判 octet-stream 拒掉**(`unzip -l` / `file` 都正确识别为 zip)
- 已 `mcp__ccd_session__spawn_task` 派发独立修复 chip:libmagic 返 octet-stream 时应 fallback 到 `_MAGIC_BYTES` 字节头硬比对
- L3 测试用 Python 脚本绕过:直接 INSERT `TenderDocument` 行 + `_extract_tender_archive(tid)` 触发解析(同 [test_tender_parse_failsoft.py](backend/tests/e2e/test_tender_parse_failsoft.py) 模式),不影响 §3 验证

---

## 2. 检测过程

### 2.1 触发
```
POST /api/projects/3709/analysis/start
{
  "version": 1,
  "agent_task_count": 27
}
```
- 触发时间:2026-04-30T09:15:34Z
- 完成时间:~2026-04-30T09:21:30Z(约 6 分钟)

### 2.2 AgentTask 结果(27 任务)
- **succeeded: 23**
- **timeout: 3** —— text_similarity (4174-4175) / text_similarity (4174-4176) / style(global)
- **skipped: 1** —— text_similarity preflight 一对(具体见 agent_tasks_v1.json)

### 2.3 timeout 分析(非 §3 引发)
- 仅 vendor-A 参与的 2 个 text_similarity PC timeout
- 同型 timeout 在 [text-sim-exact-match-bypass-real-llm-e2e-2026-04-29 README](../text-sim-exact-match-bypass-real-llm-e2e-2026-04-29/README.md) 已观察到(vendor-A 文档量 + LLM judge 上下文长度可能触发子进程超时阈值)
- 与 §3 改动无关(§3 仅在 detector 算分时调 baseline_resolver,subprocess 超时发生在 cosine 计算阶段)
- 不影响 L3 minimum-set 核心结论(B-C PC 1 个成功样本足以验证 §3 代码路径)

### 2.4 报告(AnalysisReport v=1)
见 `analysis_report_v1.json`:
- total_score: 70.83
- risk_level: high(铁证 B-C 上调)
- template_cluster_detected: false(无元数据簇)
- template_cluster_adjusted_scores: null(本次 §3 路径不产 PC-level wholesale Adjustment;wholesale 只在"PC 全 baseline 命中"时产,本数据 0 命中)

---

## 3. 关键证据 — text_similarity B-C PC

### 3.1 evidence_json 顶层
```json
{
  "algorithm": "tfidf_cosine_v1",
  "doc_role": "technical",
  "pairs_total": 40,
  "pairs_exact_match": 2,
  "pairs_plagiarism": 7,
  "pairs_template": 0,
  "pairs_generic": 28,
  "degraded": false,
  "ai_judgment": { "overall": "...", "confidence": "..." },
  "baseline_source": "none",          ← §3 新加,默认值
  "warnings": []                      ← §3 新加,≥3 投标方 → 无 L3 警示
}
```

### 3.2 samples 段级 schema(全 40 段都有)
```json
{
  "a_idx": ..., "b_idx": ..., "a_text": "...", "b_text": "...",
  "sim": 1.0, "label": "exact_match",
  "baseline_matched": false,          ← §3 新加段级
  "baseline_source": "none"           ← §3 新加段级
}
```

### 3.3 hash 比对独立验证(脚本计算 vs evidence)
- 用 `hashlib.sha256(_normalize(s.a_text).encode("utf-8")).hexdigest()` 对全 40 样本 a_text 算 hash
- 与 `TenderDocument.segment_hashes` 集合比对
- **结果:0 段命中**(`pc_text_similarity_4175_4176.json` 中每 sample 含 `_computed_hash_sha256` + `_computed_hash_in_tender` 字段供 audit)

### 3.4 is_ironclad=True 正确性论证
- B-C 命中 7 plag + 2 exact_match;触发条件:plag ≥ 3 OR ≥50字 exact_match
- exact_match 段 norm_len=73 / 131,均 ≥ 50 字 → 触发铁证
- 没有任何段命中 tender → baseline_excluded_segment_hashes 对这些段空集 → 无段被跳过
- `compute_is_ironclad` 返 True,**与 §3 改动前行为完全一致**(spec scenario "L3 投标方 ≤2 仍可独自顶铁证" 同型语义:基线缺失 ≠ 信号无效)

---

## 4. § 3 验证结论

| 维度 | 状态 | 备注 |
|---|---|---|
| baseline_resolver 加载段级 hash | ✓ | 210 tender hash 入 set,API 调用不抛 |
| evidence_json schema 扩展 | ✓ | 顶级 baseline_source / warnings + samples 段级 baseline_matched / baseline_source |
| 段 hash 命中 → 跳过 ironclad | ⚠️ 非数据 | 0 段命中,无法直接演示;L2 [test_text_sim_baseline_e2e.py](../../../backend/tests/e2e/test_text_sim_baseline_e2e.py) 5 case 全覆盖 |
| L3 立场 — 无 baseline 仍升 ironclad | ✓ | B-C is_ironclad=True 与改动前一致 |
| 老 evidence schema 兼容 | ✓ | get('baseline_source','none') / get('warnings',[]) 默认值兜底 |
| 0 回归 | ✓ | 全 unit 1332 + 全 e2e 309 全绿(commit f38aef1) |

---

## 5. 后续建议

1. **§ 3.7 标 [x] 但限定语义为"主路径功能正确"**;直接命中演示推到 §8 完整集
2. **修 tender 上传 mime 误判 bug**(已 spawn_task 派发);否则 §7 前端调 API 在生产用户的小招标 zip 会 415
3. **§ 8 完整集时,合成 vendor zip 验证 tender 命中正向效果**:把 模板.zip 的 资信标.docx 复制成 3 份 vendor zip(各加 1 句独家段)上传,触发检测,期望 2 PC 顶级 baseline_source='tender' + ≥1 sample baseline_matched=true + is_ironclad=False
4. **重跑 timeout 的 2 个 text_similarity PC**(A-B / A-C):需 bump `agent_subprocess_timeout` 或先解决 vendor-A 文档量大的根因(见 [text-sim-exact-match-bypass](../text-sim-exact-match-bypass-real-llm-e2e-2026-04-29/README.md) 同型问题)。本次 minimum-set 不阻塞 §3 落地

---

## 6. 凭证文件

| 文件 | 内容 |
|---|---|
| `tender_document.json` | TenderDocument 行(含 hash 计数 + 前 5 个 sample) |
| `agent_tasks_v1.json` | 27 个 AgentTask 全量(含 timeout 标记 + elapsed) |
| `pc_text_similarity_4175_4176.json` | B-C 唯一成功 text_similarity PC 全 evidence(40 段含 _computed_hash_in_tender 字段) |
| `analysis_report_v1.json` | AnalysisReport 行 |

---

## 7. 真 LLM 实际成本(实测)

- LLM provider: 火山引擎 Ark (`ark-code-latest`)
- 触发的 LLM 调用:
  - role_classifier × 3 vendors(parser pipeline,filename 命中后短路调用部分省略)
  - text_similarity LLM judge × 1 succeeded(B-C)+ 2 timeout(超时被取消,可能仍计费)
  - 其他 detector(metadata / error_consistency / style 等)的 LLM 调用
  - L-9 综合研判 LLM
- 估算总成本:**¥3-6**(实际 receipt 待用户从 Ark 控制台确认)
- 总时长:~6 min(detection)+ 1 min(parser)= 7 min
