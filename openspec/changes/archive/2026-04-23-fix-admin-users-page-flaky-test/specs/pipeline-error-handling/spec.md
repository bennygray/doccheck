## ADDED Requirements

### Requirement: 前端交互测试 timing 契约

前端 `userEvent`-based 交互测试(vitest + React Testing Library + `@testing-library/user-event`)在全量 `npm test -- --run` 跑下 SHALL 稳定通过,不因 vitest worker / jsdom / AST transform 资源累积导致默认 5000ms 超时。为此,涉及多次 `user.click` / `user.type` 的 async 测试 SHALL 满足以下二选一:

- **首选**:`userEvent.setup({ delay: null })`(移除 keystroke 间 microtask tick,userEvent v14 推荐方式),不改测试语义只改 timing
- **兜底**:若该测试场景需要模拟真实用户打字节奏(极少数 UX 依赖 debounce 的边缘 case),SHALL 显式提供 test-level timeout ≥15000ms(`test("...", async () => {...}, 15000)`),明确承认全量跑的资源压力

全新引入的前端交互测试(`userEvent.setup()` 调用)MUST 遵循本契约,防未来 suite 膨胀再次触发 5s 超时 flaky。

#### Scenario: AdminUsersPage 创建用户测试在全量跑下稳定绿

- **WHEN** `frontend/src/pages/admin/AdminUsersPage.test.tsx::创建用户成功` 测试的 `userEvent.setup()` 调用传入 `{ delay: null }` 参数
- **THEN** `cd frontend && npm test -- --run` 在至少连续 3 次全量跑下,该测试 pass;同时 `npm test -- --run AdminUsersPage` 隔离跑也 pass;两种模式行为一致,不再出现 `Test timed out in 5000ms` 报错
