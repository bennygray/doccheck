## ADDED Requirements

### Requirement: Word 模板支持 indeterminate 与身份信息缺失降级文案

Word 报告导出模板 SHALL 根据 `AnalysisReport.risk_level` 和项目下 bidder 的 `identity_info_status` 字段产出对应降级文案,而非硬编码"低风险/无围标"等误导性结论。

- **risk_level 分支**(`services/export/templates.py` 或 docxtpl 模板逻辑):
  - `high` / `medium` / `low`:保持现有文案(按 change 前行为)
  - `indeterminate`(honest-detection-results 新增):风险等级文案写"证据不足,无法判定";总体结论段落写 AnalysisReport.llm_conclusion 原文("证据不足,无法判定围标风险(有效信号维度全部为零)");**不**套用"经 N 维度比对均未发现异常"等描述性模板(否则与 indeterminate 语义矛盾)
- **identity_info_status 降级段落**:
  - 当项目下**任一** bidder `identity_info_status='insufficient'` 时,`error_consistency` 维度段落追加一段:"注:本维度在身份信息缺失情况下已降级判定,结论仅供参考。"
  - 若所有 bidder 都 `sufficient`,段落不追加此注

#### Scenario: 证据不足报告导出为 Word

- **WHEN** 导出 `risk_level='indeterminate'` 的报告
- **THEN** 生成的 .docx 首页/结论段落含"证据不足,无法判定";不含"低风险"或"无围标迹象"等误导字眼

#### Scenario: 身份信息缺失的 error_consistency 段落含降级提示

- **WHEN** 导出一个含 `identity_info=NULL` bidder 的项目报告
- **THEN** error_consistency 维度段落末尾含"本维度在身份信息缺失情况下已降级判定"字样

#### Scenario: 完整身份信息的报告不追加降级注

- **WHEN** 所有 bidder 都有完整 identity_info,导出报告
- **THEN** error_consistency 段落不含"已降级判定"字样(保持原内容)

#### Scenario: 历史 low/medium/high 报告导出行为不变

- **WHEN** 导出 change 前已生成的 `risk_level='low'` 报告
- **THEN** 内容与 change 前一致,无回归
