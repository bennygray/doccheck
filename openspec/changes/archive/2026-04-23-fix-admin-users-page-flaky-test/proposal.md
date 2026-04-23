## Why

`test-infra-followup-wave2` 归档时发现遗留:前端 `AdminUsersPage.test.tsx::创建用户成功` 在 **全量** `npm test -- --run` 跑时**稳定**失败(clean tree 上同失败,隔离 `npm test -- --run AdminUsersPage` 绿),报错 `Test timed out in 5000ms`。

根因:`userEvent.setup()` 默认附带 per-keystroke `setTimeout` delay,full suite 下 import 累积 + environment 启动(jsdom + antd + AST transform 285s)导致测试时钟挤压,5s 默认 timeout 不够。隔离跑时单文件资源充足,5s 绰绰有余。

**影响**:阻塞前端 CI 稳定性 + 阻塞未来前端 change 归档前的"`npm test` 全绿" 校验门(目前 113/114,每次都要人工核对"1 fail 是 pre-existing")。

## What Changes

- **修测试**:`frontend/src/pages/admin/AdminUsersPage.test.tsx::创建用户成功` 的 `userEvent.setup()` 调用改为 `userEvent.setup({ delay: null })`,移除 per-keystroke `setTimeout` delay —— userEvent v14 推荐的 non-animated interaction 方式,不改测试语义,显著降低全量跑下的累积时钟压力
- **不**同时批改其他 `userEvent.setup()` 站点:scope 锁死在出问题的那一个测试,未来若其他 case 有同型 flaky 再单独处理(避免无病例 change)
- **加 minimal spec**:`pipeline-error-handling` capability 新增 1 Requirement "前端交互测试 timing 契约" + 1 scenario,锁定"userEvent 类前端交互测试 MUST 关闭 per-keystroke delay 或 test-level timeout ≥15s",防未来引入类似 flaky

## Capabilities

### New Capabilities
(无)

### Modified Capabilities
- `pipeline-error-handling`:添加 1 ADDED Requirement "前端交互测试 timing 契约"(沿用 wave2 归档时加入的同 capability 下"测试基础设施鲁棒性契约"主题)

## Impact

**前端代码**(1 文件 2 行改动)
- `frontend/src/pages/admin/AdminUsersPage.test.tsx`:L94 附近 `userEvent.setup()` → `userEvent.setup({ delay: null })`

**spec**(1 文件 1 Requirement 追加)
- `openspec/changes/fix-admin-users-page-flaky-test/specs/pipeline-error-handling/spec.md`:1 ADDED Requirement + 1 scenario

**无后端改动,无 UI 改动,无 DB / API / 前端 route 变更**。fallback 路径(若 `delay: null` 仍偶发)= test-level `{ timeout: 15000 }` 第 3 参数,apply 期观察决定是否加。

**验收标准**:`cd frontend && npm test -- --run` 从 113/114 变 **114/114** 全绿,且多次跑稳定。
