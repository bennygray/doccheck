## 1. Impl

- [x] 1.1 [impl] 修改 `frontend/src/pages/admin/AdminUsersPage.test.tsx` L94 的 `const user = userEvent.setup();` 为 `const user = userEvent.setup({ delay: null });`(加注释说明 fix-admin-users-page-flaky-test 意图)

## 2. L1 / 前端测试

- [x] 2.1 [L1/前端] `npm test -- --run AdminUsersPage` 隔离跑 4/4 绿 in 14.13s(baseline 已绿,验 `delay: null` 不引入回归)
- [x] 2.2 [L1/前端] `npm test -- --run` 全量跑 3 次**仍稳定 fail**(113/114,`Test timed out in 5000ms`)—— 证实 `delay: null` 单独不够,触发 design D2 fallback path
- [x] 2.3 [L1/前端] Fallback 触发:追加 test-level timeout=15000ms(`test("创建用户成功", async () => {...}, 15000)`);再跑 3 次全量 **全绿 114/114**(45s × 3 次稳定,轮次耗时 45.46s / 45.29s / 45.01s,测试总量一致)

## 3. 归档前总汇

- [x] 3.1 `npm test -- --run` 全量 **114/114 连续 3 次绿**(Task 2.3 实测),稳定
- [x] 3.2 跑 [L1][L2][L3]:backend L1 baseline 1020 + L2 281/281 未动(本 change 无后端改动,零回归);前端 L1 114/114 全绿(核心验证);L3 无改动延续手工凭证
- [x] 3.3 归档前校验:Task 2.3 的 3 次连续全量绿(timeout=15000 fallback 实装)。commit message 会写清 fallback 触发
