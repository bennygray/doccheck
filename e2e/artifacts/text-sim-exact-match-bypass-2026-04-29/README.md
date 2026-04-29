# L3 凭证: text-sim-exact-match-bypass

**Change**: text-sim-exact-match-bypass
**Date**: 2026-04-29
**Base commit**: 97742fd (apply 阶段在此基础上的 in-progress 改动,未 commit)

## 目标场景(用户客户演示痛点复现)

用户在两份模板化"工程监理技术标"docx (NEW A、NEW C) 中故意 ctrl-c/ctrl-v 复制粘贴 3 段相同内容(165 / 131 / 47 字),期望系统识别围标且双栏对比 UI 高亮显示。

实测文件来源:`tmp_repro2/同样句式加在第一段/` (用户提供的客户演示原始 zip)

## 测试设置

- **Project**: id=3297 (`L3-text-sim-exact-match-bypass`)
- **Bidder A**: id=3722 (Vendor-A-PangangTech) — 上传 `供应商A.zip` (89 MB,含 7 文件,技术标 1.5 MB docx)
- **Bidder C**: id=3723 (Vendor-C-HuaXia) — 上传 `供应商C.zip` (194 MB,含 7 文件,技术标 1.18 MB docx)
- **Detection version**: v=5 (前 4 次为 cap=80 timeout / hash 旁路位置实验,见"实施过程"章节)
- **后端**: localhost:8001 (实重启后跑 uvicorn,新代码版本)
- **前端**: localhost:5173 (vite dev,dom 渲染验证)
- **LLM**: 真 LLM (本 change 选真 LLM,参考 CLAUDE.md L3 LLM mock 约定)

## 实测注入段 ground truth

| 段 | 长度 | A 文档位置 | C 文档位置 |
|---|---|---|---|
| "检查材料的保管情况..." | 165 字 | NEW A `[11]` (新加) + NEW A `[682]` (原有) | NEW C `[109]` (新加) |
| "必须坚持榜样先行..." | 131 字 | NEW A `[684]` (原有) | NEW C `[3273]` (新加) |
| "啊啊啊啊啊啊哦哦哦哦哦19988227268638386..." | 47 字 | NEW A `[89]` | NEW C `[865]` |

## L3 验收点 vs 实际(详见 `pair_comparison_v5_text_similarity.json`)

| # | 验收点 | 期望 | 实际 | 状态 |
|---|---|---|---|---|
| (a-1) | 双栏 UI 165 字 "检查材料保管" 高亮 | 3 处全亮 (A[11]+A[682]+C[109]) | 3 处全亮 `rgba(194,124,14,0.38)` | ✅ |
| (a-2) | 双栏 UI 131 字 "必须坚持榜样" 高亮 | 2 处全亮 | 1 处亮 1 处不亮 | 🟡 部分通过 |
| (a-3) | 双栏 UI 47 字 "啊啊啊..." 高亮 | 2 处亮 | 0 处亮 | ❌ 已知短段限制 |
| (b) | 原 28 对真模板段判定不变 | plagiarism/template/generic 判定保留 | 真模板段全部按 sim 高亮(法定代表人/日期/技术方案/工程计划开工时间 等) | ✅ |
| (c) | evidence_json.pairs_exact_match ≥ 1 | ≥ 1 | 2 (含工程计划开工/完工时间 hash 命中) | ✅ |
| (d) | is_ironclad = True | True | True (pairs_plagiarism=26 触发原 ≥3 规则) | ✅ |
| (e) | 总分高风险 | ≥ 60 | **86.65 / 100, 高风险, 3 条铁证** (text 86.65 + 结构 100 + 元数据·作者 100) | ✅ |

## DOM 高亮颜色证据(JS 实测)

通过 `getComputedStyle(elem.parentElement.parentElement).backgroundColor` 沿 DOM 上溯 5 层取实际背景色:

```json
{
  "检查材料的保管情况": [
    "rgba(194, 124, 14, 0.38)",   // ≥90% 深橙: A[11] 用户新加位置
    "rgba(194, 124, 14, 0.38)",   // ≥90% 深橙: A[682] 原有位置
    "rgba(194, 124, 14, 0.38)"    // ≥90% 深橙: C[109] 用户新加位置
  ],
  "必须坚持榜样先行": [
    "transparent",                 // ✗ 一处未亮 (拆段后字符串细微差异未命中 left_text_map)
    "rgba(194, 124, 14, 0.38)"    // ✓
  ],
  "啊啊啊": [
    "transparent",                 // ✗ 47 字 < MIN_PARAGRAPH_CHARS=50 被合并稀释
    "transparent"                  // ✗ 同上, 不在 evidence
  ]
}
```

## AI 综合研判文本(报告页 v=5 总览)

> 两家投标人 (3722、3723) 在文本相似度维度存在铁证 (得分86.65), 投标文件文本高度雷同, 构成围标/串标的核心证据。章节相似度 (34.27) 及价格一致性 (12.5) 提供一定辅助佐证, 但结构、元数据、错误、风格及图片等维度未见明显异常或缺乏有效信息。综合判定, 本项目围标/串标风险高, 建议启动深度核查。

## 已知短段限制(spec / handoff 已注明,留 v2 ngram 路径处理)

47 字"啊啊啊..."注入段属 corner case:

1. 段长 47 < `MIN_PARAGRAPH_CHARS=50` → 触发 `_merge_short_paragraphs` 的 buf 累积合并
2. A 合并段:"啊啊啊...攀钢集团工科工程咨询有限公司\n监理工作程序和流程"(57 字)
3. C 合并段:"啊啊啊...攀钢集团工科工程咨询有限公司\n第一节 工程进度控制的目标与原则"(64 字)
4. 两侧合并段尾部追加内容不同 → cosine ≈ 0.81 排第 102 → 被 cap=60 截断 → 不进 evidence
5. **修复方向**:在 raw body 段(segmenter 合并前)做 hash 旁路;但 L3 实测 raw 段下 LLM 处理 cap=60 段对仍触发 300s timeout(v=3 / v=4),回退到 merged 段 hash 路径
6. **正式方案**:留 v2 ngram / MinHash / shingle 路径(proposal 已显式承认过渡性,handoff 已记演进路径条目)

## 顺手修复的早存在 UI bug

L3 走查中发现 `compare.py` 的 `left_text_map` / `right_text_map` 用 dict 推导式,同字符串多次出现时**后覆盖前**,导致用户故意复制贴的 NEW A `[11]` 位置注入段被 NEW A `[682]` 覆盖,UI 在 `[11]` 不高亮、只在 `[682]` 高亮。

**修复**: `left_text_map: dict[str, list[int]]`,同字符串记录所有出现位置,派生 match 时笛卡尔积。这才让 165 字段在 NEW A `[11]` + `[682]` + NEW C `[109]` 三处全部高亮。

## 实施过程(detection version 演进)

| version | 配置 | 状态 | 备注 |
|---|---|---|---|
| v=1 | cap=80, hash 在 merged 段 | text_similarity timeout 300s | NEW 大文档 + cap=80 真 LLM 处理 prompt 过慢 |
| v=2 | cap=60, hash 在 merged 段 | succeeded 194s | 文本相似度 score=86.02 ironclad=True;但 a_idx=merged 体系前端不映射 |
| v=3 | cap=60, hash 在 raw 段(无 20 字过滤) | timeout 302s | raw 段 hash 笛卡尔积小但 LLM 处理仍长 |
| v=4 | cap=60, hash 在 raw 段(20 字过滤) | timeout 302s | 同 v=3 |
| **v=5** | **cap=60, hash 在 merged 段, segmenter 暴露 anchor 转 raw paragraph_index** | **succeeded 289s** | **本次 L3 凭证基线** |

## 凭证文件清单

- `README.md` (本文件)
- `pair_comparison_v5_text_similarity.json` — v=5 文本相似度 PairComparison 完整 evidence_json (45 KB)
- `injection_samples_v5.json` — 注入段相关 samples 摘录
- `analysis_report_v5.json` — v=5 总分与风险等级

> **注**: Claude_in_Chrome MCP 截图工具 `save_to_disk=true` 在本项目环境下未返回磁盘路径(仅以 image 内联返回),L3 PNG 凭证缺失。本次以"DOM 实测高亮颜色 JSON + 完整 evidence_json + AI 综合研判文本"作为等价产品验证证据。
