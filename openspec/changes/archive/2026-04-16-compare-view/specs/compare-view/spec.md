## ADDED Requirements

### Requirement: 文本对比 API
系统 SHALL 提供 `GET /api/projects/{pid}/compare/text` endpoint,接受 `bidder_a`(必填)、`bidder_b`(必填)、`doc_role`(选填)、`version`(选填)查询参数,返回两个投标人同角色文档的段落列表和相似段落匹配关系。

- `version` 未指定时 SHALL 取该项目最新 AnalysisReport 的 version
- `doc_role` 未指定时 SHALL 取该 pair 在 text_similarity 维度 score 最高的 doc_role
- 响应 SHALL 包含:`left_paragraphs[]`(bidder_a 文档段落)、`right_paragraphs[]`(bidder_b 文档段落)、`matches[]`(相似段落对,含 sim 和 label)、`available_roles[]`(可选角色列表)
- `matches` 数据来源 SHALL 是 PairComparison(dimension=text_similarity)的 `evidence_json.samples`
- 段落来源 SHALL 是 DocumentText(location='body')

#### Scenario: 正常文本对比
- **WHEN** 请求 `GET /compare/text?bidder_a=1&bidder_b=2&doc_role=commercial&version=1`
- **THEN** 返回 200,body 含 left_paragraphs(bidder_a 的 commercial 文档段落)、right_paragraphs(bidder_b 的 commercial 文档段落)、matches(evidence_json.samples 映射)、available_roles 列表

#### Scenario: 未指定 doc_role 取最高分
- **WHEN** 请求 `GET /compare/text?bidder_a=1&bidder_b=2&version=1` 且该 pair 有 commercial(score=75) 和 technical(score=60) 两条 PairComparison
- **THEN** 返回 200,自动选择 commercial 角色的对比数据

#### Scenario: 无同角色文档
- **WHEN** 请求的 doc_role 对应的 BidDocument 不存在于任一 bidder
- **THEN** 返回 200,left_paragraphs 或 right_paragraphs 为空数组,matches 为空数组

#### Scenario: 无检测结果
- **WHEN** 该 pair 在 text_similarity 维度无 PairComparison 记录
- **THEN** 返回 200,matches 为空数组,段落仍正常返回(审查员可人工对照)

#### Scenario: 超大文档分页
- **WHEN** 段落数 > limit 参数(默认 5000)
- **THEN** 返回前 limit 条段落,响应含 `has_more: true` 和 `total_count`

---

### Requirement: 报价对比 API
系统 SHALL 提供 `GET /api/projects/{pid}/compare/price` endpoint,接受 `version`(选填)查询参数,返回全项目投标人报价矩阵。

- 矩阵行 SHALL 是报价项(按 item_name 对齐)
- 矩阵列 SHALL 是项目所有 Bidder
- 每行 SHALL 包含:item_name、unit、各投标人单价(unit_price)、均价(mean)、各投标人偏差百分比(deviation)
- 偏差 SHALL 计算为 `(price - mean) / mean * 100`,mean=0 时偏差为 null
- 响应 SHALL 包含底部总报价行:各投标人 `SUM(total_price)`
- 报价项对齐 SHALL 优先使用 price_consistency 维度 PairComparison evidence 的对齐信息;无检测结果时退化为 item_name NFKC 归一精确匹配

#### Scenario: 正常报价矩阵
- **WHEN** 请求 `GET /compare/price?version=1`,项目有 3 个投标人各 10 条报价项
- **THEN** 返回 200,body 含 bidders(3 个)、items(对齐后的报价项列表,每项含 prices_by_bidder 和 deviations_by_bidder)、totals_by_bidder

#### Scenario: 投标人无报价数据
- **WHEN** 某投标人无 PriceItem 记录
- **THEN** 该投标人在矩阵中所有单元格值为 null,前端显示"-"

#### Scenario: 未运行检测时退化对齐
- **WHEN** 无 price_consistency 维度的 PairComparison 记录
- **THEN** 退化为 item_name NFKC 归一精确匹配对齐,响应正常返回

#### Scenario: 空项目
- **WHEN** 项目无投标人或无报价数据
- **THEN** 返回 200,bidders 或 items 为空数组

---

### Requirement: 元数据对比 API
系统 SHALL 提供 `GET /api/projects/{pid}/compare/metadata` endpoint,接受 `version`(选填)查询参数,返回全项目投标人元数据矩阵。

- 矩阵行 SHALL 是固定 8 字段:author / last_saved_by / company / app_name / app_version / template / doc_created_at / doc_modified_at
- 矩阵列 SHALL 是项目所有 Bidder
- 每个 Bidder SHALL 取主文档(role 优先级:commercial > technical > proposal > 其他,同角色取 id 最小)的 DocumentMetadata
- 每个单元格 SHALL 标记 `is_common`(在后端通用值列表中 或 ≥80% 投标人持有相同值)
- 相同值 SHALL 分配相同的 `color_group` 索引(供前端着色)
- 时间字段 SHALL 格式化为 ISO 8601 字符串

#### Scenario: 正常元数据矩阵
- **WHEN** 请求 `GET /compare/metadata?version=1`,项目有 5 个投标人
- **THEN** 返回 200,body 含 bidders(5 个)、fields(8 行,每行含 values_by_bidder,每个值含 value/is_common/color_group)

#### Scenario: 通用值标记
- **WHEN** 某 bidder 的 author 为 "Administrator"
- **THEN** 该单元格 is_common=true

#### Scenario: 高频值标记
- **WHEN** 5 个投标人中 4 个的 app_name 为 "Microsoft Word"
- **THEN** 4/5=80%,这 4 个单元格 is_common=true

#### Scenario: 投标人无元数据
- **WHEN** 某 Bidder 无 BidDocument 或其 BidDocument 无 DocumentMetadata
- **THEN** 该投标人所有字段值为 null

---

### Requirement: 文本对比前端页面
系统 SHALL 提供文本对比页面(`/reports/:pid/:ver/compare/text`),以左右双栏形式展示两个投标人同角色文档的段落对比。

- 左栏 SHALL 显示 bidder_a 文档段落,右栏显示 bidder_b 文档段落
- 相似段落 SHALL 用黄色高亮,深浅 SHALL 映射相似度值(sim 越高越深)
- hover 高亮段落 SHALL 显示相似度百分比 tooltip
- 点击高亮段落 SHALL 让对侧栏滚动到对应的匹配段落
- 左右两栏 SHALL 支持同步滚动
- 页面 SHALL 提供角色切换下拉(从 available_roles 构建)
- 无同角色文档时 SHALL 显示"无可对比的同类文档"空状态
- 段落列表 SHALL 使用虚拟滚动渲染

#### Scenario: 正常文本对比渲染
- **WHEN** 用户从 ComparePage 点击某 text_similarity pair 进入文本对比页
- **THEN** 左右双栏显示两侧文档段落,matches 对应的段落黄色高亮

#### Scenario: 点击高亮跳转
- **WHEN** 用户点击左栏某高亮段落(a_idx=10,对应 b_idx=15)
- **THEN** 右栏自动滚动到 paragraph_index=15 的段落位置

#### Scenario: 角色切换
- **WHEN** 用户从下拉选择不同 doc_role
- **THEN** 页面重新请求该角色的对比数据并刷新显示

#### Scenario: 空状态
- **WHEN** 某角色无文档数据
- **THEN** 显示"无可对比的同类文档"提示

---

### Requirement: 报价对比前端页面
系统 SHALL 提供报价对比页面(`/reports/:pid/:ver/compare/price`),以矩阵表格展示全项目投标人报价对比。

- 表格行 SHALL 是报价项(item_name),列 SHALL 是投标人
- 单元格 SHALL 显示单价(unit_price),偏差 <1% 的单元格 SHALL 标红
- 无报价数据的单元格 SHALL 显示"-"
- 表格 SHALL 支持按任意列排序
- 表格底部 SHALL 显示总报价对比行
- 页面 SHALL 提供"只看异常项" toggle,开启时仅显示含偏差 <1% 单元格的行
- 默认全量展开所有报价项

#### Scenario: 正常报价矩阵渲染
- **WHEN** 用户进入报价对比页,项目有 3 个投标人 20 条报价项
- **THEN** 表格显示 20 行 × 3+2 列(item_name + 3 投标人 + 偏差列),底部总报价行

#### Scenario: 异常项标红
- **WHEN** 某单元格偏差绝对值 < 1%
- **THEN** 该单元格背景标红

#### Scenario: 只看异常项 toggle
- **WHEN** 用户开启"只看异常项" toggle
- **THEN** 表格仅显示含至少一个偏差 <1% 单元格的行 + 总报价行

#### Scenario: 列排序
- **WHEN** 用户点击某投标人列头
- **THEN** 表格按该列单价升序/降序排列

---

### Requirement: 元数据对比前端页面
系统 SHALL 提供元数据对比页面(`/reports/:pid/:ver/compare/metadata`),以矩阵表格展示全项目投标人元数据对比。

- 行 SHALL 是元数据字段名,列 SHALL 是投标人
- 相同值的单元格 SHALL 按 color_group 着色(同组同色)
- is_common=true 的单元格 SHALL 标灰并显示 tooltip "通用值,已过滤"
- template 字段匹配 SHALL 用醒目标记(与硬件指纹同等权重)
- 时间字段 SHALL 格式化为"YYYY-MM-DD HH:mm"易读格式
- 无元数据的单元格 SHALL 显示"-"

#### Scenario: 正常元数据矩阵渲染
- **WHEN** 用户进入元数据对比页,项目有 5 个投标人
- **THEN** 表格显示 8 行 × 5 列,相同值同色高亮

#### Scenario: 通用值标灰
- **WHEN** 某投标人 author 为 "Administrator"(is_common=true)
- **THEN** 该单元格灰色显示,hover 出现"通用值,已过滤" tooltip

#### Scenario: 硬件指纹/模板匹配标红
- **WHEN** 多个投标人的 template 字段值相同且非通用值
- **THEN** 这些单元格用红色醒目标记

---

### Requirement: ComparePage Tab 导航
现有 ComparePage SHALL 增加顶部 Tab 栏,支持切换到三类对比视图。

- Tab 栏 SHALL 包含:对比总览(当前 pair 列表)| 报价对比 | 元数据对比
- 对比总览 Tab 中 dimension=text_similarity 的 pair 行 SHALL 增加"查看文本对比"入口链接
- 点击"查看文本对比"SHALL 跳转到 `/reports/:pid/:ver/compare/text?bidder_a=X&bidder_b=Y`
- 点击"报价对比"/"元数据对比" Tab SHALL 跳转到对应路由

#### Scenario: Tab 切换
- **WHEN** 用户在 ComparePage 点击"报价对比" Tab
- **THEN** 页面导航到 `/reports/:pid/:ver/compare/price`

#### Scenario: 文本对比入口
- **WHEN** pair 列表中有 dimension=text_similarity 且 score > 0 的行
- **THEN** 该行显示"查看文本对比"链接图标,点击跳转到文本对比页(携带 bidder_a/bidder_b 参数)
