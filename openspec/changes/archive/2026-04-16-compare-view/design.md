## Context

M4 C16。C15 report-export 已交付报告总览/维度明细/人工复核/Word 导出。检测层(C6~C14)已产出完整 PairComparison evidence 数据,文档解析层(C5)已持久化 DocumentText / PriceItem / DocumentMetadata。现在建三类对比视图,让审查员能直观查看原始数据级别的对比。

**现有前端路由**(C15 建):
- `/reports/:pid/:ver` → ReportPage
- `/reports/:pid/:ver/dim` → DimensionDetailPage
- `/reports/:pid/:ver/compare` → ComparePage(pair 列表)
- `/reports/:pid/:ver/logs` → AuditLogPage

**现有 ComparePage**:展示 PairComparison 列表(dimension / bidder_a / bidder_b / score / is_ironclad / evidence_summary),按 score 降序,支持 sort + limit。

## Goals / Non-Goals

**Goals:**
- 实现 US-7.1~7.3 三类对比视图(文本/报价/元数据)
- 后端 3 个只读聚合 endpoint,不写入数据
- 前端 3 个新页面 + 改造现有 ComparePage 增加 Tab 导航
- 大数据量场景前端虚拟滚动 + 后端分页兜底

**Non-Goals:**
- 不做实时 diff 算法(复用检测层 evidence)
- 不做 section_similarity 级对比(只用 text_similarity evidence)
- 不做报价归一化(币种/含税,延续 C11 决策)
- 不做跨项目对比
- 不改任何检测层 / 导出层代码

## Decisions

### D1 文本对比数据来源

复用 PairComparison(dimension=text_similarity)的 `evidence_json.samples` 数组。每个 sample 含 `{a_idx, b_idx, a_text, b_text, sim, label}`(最多 10 对)。后端 endpoint 额外读两侧 DocumentText(location='body')全量段落,拼装为 `left_paragraphs[] + right_paragraphs[] + matches[]`。

`a_idx`/`b_idx` 对应 DocumentText.paragraph_index。前端按 matches 高亮,highlight 深浅映射 sim 值。

**为什么不重算**:Q4 决策;重算引入新算法(与检测结果不一致) + 实时计算慢 + scope 溢出。top 10 samples 足够审查员定位关键段落。

### D2 文本对比 doc_role 切换

一对 (bidder_a, bidder_b) 可能有多条 PairComparison(每个 doc_role 一条)。endpoint 接受 `doc_role` 查询参数,前端提供角色切换下拉。endpoint 还返回可用 doc_role 列表(从 PairComparison WHERE dimension='text_similarity' AND bidder_a/b 匹配 DISTINCT evidence_json->>'doc_role')。

无 doc_role 参数时默认取 score 最高的那条。

### D3 报价对比矩阵构建

全项目级。后端聚合逻辑:
1. 查询项目所有 Bidder
2. 查询所有 PriceItem,按 `(sheet_name, row_index, item_name)` 聚合为"报价项行"
3. 对齐策略:复用 C11 两阶段对齐结果 — 先查 PairComparison(dimension=price_consistency) 的 evidence_json 取 alignment 信息;若无检测结果,退化为 `item_name` 精确匹配
4. 每行计算均价 + 各投标人偏差百分比 `(price - mean) / mean * 100`
5. 底部追加总报价行(各投标人 `SUM(total_price)`)

返回结构:`{bidders[], items[{name, unit, quantities, prices_by_bidder, deviations_by_bidder, mean_price}], totals_by_bidder}`。

### D4 报价对齐退化策略

理想情况:C11 price_consistency 检测已跑,evidence_json 含对齐信息。但如果:
- 检测未跑(用户直接访问对比页):退化为按 `item_name` NFKC 归一后精确匹配
- 报价项 item_name 全空:按 `(sheet_name, row_index)` 位置对齐(同模板假设)

这两个退化路径保证"未检测也能看对比"。

### D5 元数据矩阵构建

全项目级。后端聚合:
1. 查询项目所有 Bidder → 每个 Bidder 的所有 BidDocument → JOIN DocumentMetadata
2. 矩阵行 = 固定 8 字段:`author / last_saved_by / company / app_name / app_version / template / doc_created_at / doc_modified_at`
3. 每个 Bidder 取**主文档**(role 优先级:commercial > technical > proposal > 其他)的元数据;若有多份同角色文档取第一份
4. 每个单元格标记 `is_common`:通用值列表(后端常量)+ 匹配计数(≥ 项目投标人数 80% 的值也视为通用)
5. 相同值分组:按 (field, value) 聚合,同组用相同颜色 index 前端着色

返回结构:`{bidders[], fields[{name, values_by_bidder[{value, is_common, color_group}]}]}`。

### D6 元数据通用值列表

后端常量 `METADATA_COMMON_VALUES`:
```python
METADATA_COMMON_VALUES = {
    "author": {"Administrator", "admin", "User", "Author", ""},
    "last_saved_by": {"Administrator", "admin", "User", ""},
    "company": {""},
    "app_name": set(),  # 不过滤软件名(软件名匹配本身就是信号)
}
```

匹配时 NFKC + casefold + strip 后比较。值为 None/空串统一视为通用。

### D7 前端路由与导航

新增路由:
- `/reports/:pid/:ver/compare/text` → TextComparePage(query: `bidder_a`, `bidder_b`, `doc_role`)
- `/reports/:pid/:ver/compare/price` → PriceComparePage
- `/reports/:pid/:ver/compare/metadata` → MetaComparePage

改造 ComparePage:
- 顶部 Tab 栏:`对比总览`(当前 pair 列表) | `报价对比` | `元数据对比`
- pair 列表中 dimension=text_similarity 的行增加"查看文本对比"链接图标

### D8 后端 API 设计

三个 endpoint 统一挂在 `/api/projects/{project_id}/compare/` 前缀:

```
GET /api/projects/{pid}/compare/text?bidder_a={id}&bidder_b={id}&doc_role={role}&version={ver}
GET /api/projects/{pid}/compare/price?version={ver}
GET /api/projects/{pid}/compare/metadata?version={ver}
```

version 选填,默认取最新(MAX version from AnalysisReport)。text 的 bidder_a/bidder_b 必填。

后端路由文件:`backend/app/api/routes/compare.py`,注册到 `/api/projects/{project_id}/compare` 前缀。

### D9 前端虚拟滚动

文本对比双栏:用 `@tanstack/react-virtual` 实现虚拟滚动。两栏共享滚动位置(synchronized scroll)。段落高度不等 → 用 `estimateSize` + dynamic measurement。

报价/元数据表格:行数通常 < 500,不需要虚拟化;若实测慢再加(YAGNI)。

### D10 超大边界兜底

文本对比 endpoint 加 `limit`(默认 5000)+ `offset`(默认 0)参数。段落数 > 5000 时返回 `has_more: true` + `total_count`,前端显示"加载更多"按钮。

报价/元数据:投标人数通常 < 20,报价项 < 500,不做分页(单次返回全量 JSON 几十 KB)。

### D11 测试计划

- **L1 后端 pytest**:3 endpoint 各 ~5 用例(正常/空数据/缺检测结果退化/参数校验) ≈ 15
- **L1 前端 Vitest**:3 页面组件渲染 + Tab 切换 + toggle ≈ 10
- **L2 后端 E2E**:3 Scenario(text + price + metadata 全链路,含 seed 数据) ≈ 3
- **L3**:手工凭证(Docker kernel-lock 未解)

### D12 follow-ups(不做)

- 字符级 diff(段内高亮)→ 独立 change 或 follow-up
- 报价 LLM 语义对齐 item_name → 延续 C11 follow-up
- 元数据通用值管理 UI(admin 可编辑白名单)→ C17 admin
- 对比页面导出为图片/PDF → follow-up

## Risks / Trade-offs

- **[evidence samples 上限 10]** → 文本对比最多高亮 10 对段落。对于大文档可能漏掉一些相似段落。**缓解**:10 对已是最高相似度 pairs,审查员关注的就是这些;要完整数据可看维度明细的 evidence 展开。
- **[报价对齐退化]** → 未跑检测时 item_name 精确匹配可能对不齐(同项不同名)。**缓解**:前端提示"建议先运行检测以获得更准确的对齐";实际使用流程是先检测再查看。
- **[元数据主文档选择]** → 一个投标人可能有多份同角色文档,只取第一份可能选错。**缓解**:按 bid_document.id ASC 取最早上传的(通常是主文件);follow-up 可支持文档选择器。
- **[前端新增依赖]** → `@tanstack/react-virtual`。**缓解**:生产级库,MIT 协议,bundle ~5KB gzip,社区活跃。
