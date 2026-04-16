## MODIFIED Requirements

### Requirement: 文本对比前置条件
text_similarity agent 的 preflight 字数下限 `TEXT_SIM_MIN_DOC_CHARS` SHALL 默认 300（原 500）。当任一侧选中文档总字符数 < 300 时 SHALL skip 该 agent。

#### Scenario: 300-500 字文档不再被跳过
- **WHEN** 两个投标人的 technical 文档各有 350 字（大于 300，小于原阈值 500）
- **THEN** text_similarity agent SHALL 正常执行（不 skip），产出 PairComparison 记录，文本对比页面 SHALL 显示左右面板

#### Scenario: 极短文档仍被跳过
- **WHEN** 任一侧文档总字符数 < 300
- **THEN** text_similarity agent SHALL skip，summary 为"文档过短无法对比"
