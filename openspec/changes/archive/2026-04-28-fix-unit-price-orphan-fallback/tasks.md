## 1. 实施 fallback 逻辑

- [x] 1.1 [impl] 修改 `_find_pricing_xlsx`(leader 选举):先查 `file_role='pricing'`,空时再查 `file_role='unit_price'`(顺序两次 SELECT,互斥)
- [x] 1.2 [impl] 修改 `_find_all_pricing_xlsx`(回填遍历):同样的 fallback 模式;返回的列表内部不混合两类
- [x] 1.3 [impl] 在两个函数 docstring 标注 fallback 语义与"单 bidder 单类不变量",指向 spec MODIFIED Requirement
- [x] 1.4 [impl] 不改任何调用方(`run_pipeline.py` 主流程对 helper 返回值的使用方式不变)

## 2. L1 单元测试

- [x] 2.1 [L1] 在 `backend/tests/unit/test_pricing_xlsx_fallback.py` 加 4 个 case 覆盖 4 个 Scenario(纯 pricing / 纯 unit_price fallback / 两者都有优先 pricing / 都没有返空)
- [x] 2.2 [L1] 同上 4 个 case 也覆盖 `_find_pricing_xlsx`(单文件 leader 选举版本)
- [x] 2.3 [L1] 加对称性 case `test_leader_and_fill_symmetric`(parametrize 3 fixture),验证 leader 选出的 path 必然属于 fill 列表 + 两者 file_role 一致 + 单类不变量
- [x] 2.4 [L1] 加 sheet mismatch regression `test_unit_price_fallback_then_sheet_mismatch_fails`:fallback 命中 unit_price xlsx 但 sheet 名不匹配 → items_count=0 + partial_failed_sheets 含"未找到"
- [x] 2.5 [L1] 跑 `pytest tests/unit/test_pricing_xlsx_fallback.py -v` 全绿(12/12 passed)

## 3. L2 API 级 e2e 测试

- [x] 3.1 [L2] 加 `test_pipeline_unit_price_fallback`:2 家 bidder 全 unit_price → 全 priced + aggregate 返 2 条(实施记录:取 2 家而非 3 家,多 bidder 聚合不变量在 2 即可暴露;3 家在 L3 真实 UI 覆盖)
- [x] 3.2 [L2] 加 `test_pipeline_mixed_role_no_double_count`:1 家 bidder 含 pricing+unit_price 两份 xlsx → 仅 pricing 进回填;集成跑 `price_overshoot.run` 断言 score=0 + has_iron_evidence=False(混算会触发 SUM=150>120 误报,实际 SUM=100 不触发)
- [x] 3.3 [L2] 跑 `pytest tests/e2e/test_parser_pipeline_api.py -v -k "fallback or no_double_count"` 全绿(2/2 passed)

## 4. L3 UI 级真实复现

- [x] 4.1 [L3] backend(8001) + frontend(5173)已运行,验证两端可达
- [x] 4.2 [L3] 用 Claude_in_Chrome MCP 登录 `http://localhost:5173`,创建项目 `e2e-fallback-2026-04-28`(id=3066,L3-FALLBACK-001,maxprice=500 万)
- [x] 4.3 [L3] 上传 3 个供应商 zip(透明记录:Chrome 拒绝 MCP 程序化 file_upload,改 API 上传;详见 artifacts README "操作变通"段),pipeline 在 ~3 分钟跑完,bidder_ids=[3431,3432,3433]
- [x] 4.4 [L3] 截图保存到 `e2e/artifacts/fix-unit-price-orphan-fallback-2026-04-28/`:01-项目详情(3 家 priced + 100% 进度 + 报价规则) + 02-供应商A 文件列表对话框
  - 注:本地 ark 不复现 unit_price 误判,L3 仅验证主路径无回归;fallback 路径覆盖在 L1+L2(详见 README "L3 范围与限制"段)
- [x] 4.5 [L3] 写 `e2e/artifacts/.../README.md`,含期望 vs 实际对照表 + HEAD commit hash + L3 范围说明 + 操作变通透明记录
- [x] 4.6 [L3] DB 查证:3 家 priced + 各 7 行 price_items + 三家 SUM 不同(1368000/1458000/2024400)→ 无重复求和;完整证据 → `db_evidence.json`

## 5. 文档与归档

- [x] 5.1 [impl] 更新 `docs/handoff.md`:section 1 表新当前 change 行 + 最新 commit + 4 条 follow-up(跨模型 LLM 一致性 / unit_price 角色定位 / aggregate 分桶 / L3 fallback UI 真验证);+ `.gitignore` 加 `!e2e/artifacts/fix-unit-price-orphan-fallback-*` 白名单
- [x] 5.2 [impl] `git status -uall` 检查通过:0 个 .env / .env.* / api key / credential / secret / dump 文件;无关 untracked 文件(leftover docs/e2e 脚本)需归档时显式 `git add` 排除

## 6. 总汇

- [x] 6.1 跑 [L1][L2][L3] 全部测试,全绿:L1 12/12(本 change 新增) + L2 7/7(本 change 新增 2 + 既有 5 同跑通过,确认无 cross-test 回归) + L3 真实 UI walkthrough 主路径无回归 + 凭证 4 文件齐
