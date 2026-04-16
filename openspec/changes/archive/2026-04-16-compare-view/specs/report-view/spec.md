## MODIFIED Requirements

### Requirement: ComparePage 对比入口页
ComparePage(`/reports/:pid/:ver/compare`)SHALL 在现有 PairComparison 列表基础上增加顶部 Tab 导航栏,支持切换到报价对比和元数据对比视图。

- Tab 栏 SHALL 包含三个选项:"对比总览"(默认激活,显示现有 pair 列表)、"报价对比"、"元数据对比"
- dimension=text_similarity 的 pair 行 SHALL 增加"查看文本对比"入口链接图标
- "报价对比"/"元数据对比" Tab SHALL 导航到对应子路由
- 现有 pair 列表功能(排序、limit)SHALL 保持不变

#### Scenario: Tab 导航
- **WHEN** 用户在 ComparePage 点击"报价对比" Tab
- **THEN** 页面导航到 `/reports/:pid/:ver/compare/price`

#### Scenario: 文本对比入口链接
- **WHEN** pair 列表中存在 dimension=text_similarity 且 score > 0 的行
- **THEN** 该行末尾显示"查看文本对比"图标链接,点击跳转到 `/reports/:pid/:ver/compare/text?bidder_a={bidder_a_id}&bidder_b={bidder_b_id}`

#### Scenario: 非 text_similarity 行无入口
- **WHEN** pair 行的 dimension 不是 text_similarity
- **THEN** 该行不显示"查看文本对比"链接
