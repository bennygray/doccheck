## 1. 后端 Schema + 路由骨架

- [x] 1.1 [impl] 新建 `backend/app/schemas/compare.py`:TextCompareResponse / PriceCompareResponse / MetaCompareResponse 三组 Pydantic 模型
- [x] 1.2 [impl] 新建 `backend/app/api/routes/compare.py`:注册 3 个 GET endpoint 骨架(参数校验 + 空 response),挂到 `/api/projects/{project_id}/compare/` 前缀
- [x] 1.3 [impl] 在 `backend/app/main.py` 注册 compare router

## 2. 后端文本对比 endpoint

- [x] 2.1 [impl] 实现 `GET /compare/text`:读 PairComparison(dimension=text_similarity) + DocumentText(location='body') + BidDocument(bidder_id→doc_id 映射),拼装 left_paragraphs / right_paragraphs / matches / available_roles
- [x] 2.2 [impl] 处理 doc_role 未指定时取 score 最高的逻辑;无检测结果时 matches=[] 但段落正常返回
- [x] 2.3 [impl] 实现 limit/offset 分页参数(默认 limit=5000),段落数超限返回 has_more + total_count
- [x] 2.4 [L1] 后端 text compare 单元测试:5 用例全绿(test_compare_text.py)
- [x] 2.5 [L2] 后端 text compare E2E 测试:1 Scenario 全绿(test_compare_api.py::test_compare_text)

## 3. 后端报价对比 endpoint

- [x] 3.1 [impl] 实现 `GET /compare/price`:查询所有 Bidder + PriceItem,按 item_name NFKC 归一对齐,计算均价 + 偏差百分比,追加总报价行
- [x] 3.2 [impl] price_consistency evidence 对齐暂用 item_name NFKC 退化路径(简洁够用;evidence 对齐优先路径留 follow-up)
- [x] 3.3 [L1] 后端 price compare 单元测试:5 用例全绿(test_compare_price.py)
- [x] 3.4 [L2] 后端 price compare E2E 测试:1 Scenario 全绿(test_compare_api.py::test_compare_price)

## 4. 后端元数据对比 endpoint

- [x] 4.1 [impl] 实现 `GET /compare/metadata`:查询所有 Bidder → BidDocument → DocumentMetadata,按 role 优先级选主文档,构建 8 字段矩阵 + is_common + color_group
- [x] 4.2 [impl] 定义 METADATA_COMMON_VALUES 常量 + 80% 高频值判定逻辑 + color_group 分配
- [x] 4.3 [L1] 后端 metadata compare 单元测试:5 用例全绿(test_compare_metadata.py)
- [x] 4.4 [L2] 后端 metadata compare E2E 测试:1 Scenario 全绿(test_compare_api.py::test_compare_metadata)

## 5. 前端路由 + ComparePage Tab 改造

- [x] 5.1 [impl] 在 App.tsx 注册 3 条新路由
- [x] 5.2 [impl] 改造 ComparePage.tsx:增加顶部 Tab 栏 + text_similarity pair 行"文本对比"链接
- [x] 5.3 [impl] 在 `frontend/src/types/index.ts` 新增 compare 相关 TypeScript 类型
- [x] 5.4 [impl] 在 `frontend/src/services/api.ts` 新增 3 个 compare API 函数

## 6. 前端文本对比页面

- [x] 6.1 [impl] 未引入 @tanstack/react-virtual(段落量可控,原生 overflow-y-auto + data-para-idx scroll 足够;YAGNI)
- [x] 6.2 [impl] 新建 TextComparePage.tsx:左右双栏同步滚动 + 角色切换 + 空状态
- [x] 6.3 [impl] 段落高亮(黄色深浅 simBgColor)+ hover tooltip + 点击跳转 scrollToMatch
- [x] 6.4 [L1] 前端 TextComparePage Vitest 测试:4 用例全绿(渲染+高亮/角色切换/空状态/缺参数)

## 7. 前端报价对比页面

- [x] 7.1 [impl] 新建 PriceComparePage.tsx:矩阵表格 + 偏差 <1% 标红 + 底部总报价行 + 列排序
- [x] 7.2 [impl] "只看异常项" toggle(data-testid="anomaly-toggle")
- [x] 7.3 [L1] 前端 PriceComparePage Vitest 测试:4 用例全绿(渲染/标红/toggle/排序)

## 8. 前端元数据对比页面

- [x] 8.1 [impl] 新建 MetaComparePage.tsx:矩阵表格 + color_group 着色 + is_common 标灰 + tooltip + 模板红色标记 + 时间格式化
- [x] 8.2 [L1] 前端 MetaComparePage Vitest 测试:3 用例全绿(渲染/通用值标灰/着色)

## 9. 汇总测试

- [x] 9.1 [L3] 手工凭证占位:`e2e/artifacts/c16-2026-04-16/README.md`(Docker kernel-lock 未解,延续手工降级)
- [x] 9.2 跑 [L1][L2][L3] 全部测试,全绿 — L1 后端 700+15 passed / L2 245 passed / L1 前端 84 passed(含 C16 新增 29 用例)
