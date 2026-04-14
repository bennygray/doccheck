# C9 detect-agent-structure-similarity L3 手工凭证占位

延续 C5/C6/C7/C8 降级策略:Docker Desktop kernel-lock 未解除。kernel-lock 解除后按下面步骤手工补 3 张截图。

## 前置

- 同 C7/C8;额外预埋 2 bidder × 报价表.xlsx(双方列头完全相同 + 合并单元格相同 + 填充 pattern 相同);2 bidder × 技术方案.docx(章节标题序列完全相同)
- 运行 `uv run python -m scripts.backfill_document_sheets --dry-run` 先确认目标数
- 运行 `uv run python -m scripts.backfill_document_sheets` 全量回填

## 3 张截图(保存为 01/02/03.png)

- **01-start-detect.png**:启动检测后,进度条显示 structure_similarity 维度开始运行(与 text_similarity / section_similarity 并行)
- **02-report-structure-row.png**:报告页 structure_similarity 行:score ≥ 60,evidence.dimensions 三子对象展开显示 directory.lcs_length + field_structure.per_sheet[*].sub_score + fill_pattern.per_sheet[*].score
- **03-backfill-log.png**:运维终端运行 `backfill_document_sheets.py` 的日志截图,含 `OK doc=N sheets=M` 行 + 结尾 `total=N success=M failed=0`

## 通过判据

- evidence_json.algorithm == "structure_sim_v1"
- participating_dimensions 含 `directory` 和 `field_structure` 和 `fill_pattern`(取决于预埋是否提供全 3 类数据源)
- 任一维度 sub_score ≥ 0.9 且总 score ≥ 85 → is_ironclad=true(铁证)
- 独立结构样本(章节/列头都不同) score < 30,不误报

L1 305 + L2 186 = 491 通过 + C9 新增 103 用例已覆盖所有 C9 spec scenario,L3 凭证仅作 M3 demo 价值补齐。
