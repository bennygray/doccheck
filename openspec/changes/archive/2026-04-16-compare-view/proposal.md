## Why

M4 第 2 个 change(C16)。C15 report-export 已交付报告总览/维度明细/人工复核/Word 导出四项能力,但审查员仍无法直观对比两个投标人的原始文档内容。US-7.1~7.3 定义了三类对比视图(文本/报价/元数据),是 M4 "可交付" 判据的核心组成部分。检测层(C6~C14)已产出完整的 PairComparison evidence 数据,文档解析层(C5)已持久化 DocumentText / PriceItem / DocumentMetadata,数据就绪,现在建视图。

## What Changes

- **新增文本对比视图(US-7.1)**:pair 级,左右双栏显示两个投标人同角色文档段落,复用检测层 `evidence_json.similar_pairs` 高亮相似段落,支持同步滚动、点击跳转、角色切换
- **新增报价对比视图(US-7.2)**:全项目级,行=报价项 列=投标人 矩阵表格,偏差 <1% 标红,底部总报价行,支持按列排序 + "只看异常项" toggle
- **新增元数据对比视图(US-7.3)**:全项目级,行=元数据字段 列=投标人 矩阵表格,相同值按组着色,白名单值标灰,硬件指纹红色标记
- **新增后端 3 个 compare endpoint**:只读聚合查询,不写入任何数据
- **改造现有 ComparePage**:增加顶部 Tab(对比总览 / 报价对比 / 元数据对比),pair 列表行增加"查看文本对比"入口链接

## Capabilities

### New Capabilities
- `compare-view`: 三类对比视图(文本/报价/元数据)的后端聚合 API + 前端展示页

### Modified Capabilities
- `report-view`: ComparePage 增加 Tab 导航(对比总览 → 报价对比 / 元数据对比)+ pair 行增加文本对比入口链接

## Impact

- **后端新增**:`backend/app/api/routes/compare.py`(3 个 GET endpoint)+ `backend/app/schemas/compare.py`(响应模型)
- **前端新增**:3 个页面组件(`TextComparePage` / `PriceComparePage` / `MetaComparePage`)+ 路由注册
- **前端改动**:`ComparePage.tsx` 增加 Tab 导航 + pair 行入口链接;`App.tsx` 增加 3 条路由
- **依赖**:无新增后端依赖;前端可能引入虚拟滚动库(如 `@tanstack/react-virtual`)
- **不动**:C6~C15 检测层 / 导出层 / 数据库模型 / 现有 API 契约
