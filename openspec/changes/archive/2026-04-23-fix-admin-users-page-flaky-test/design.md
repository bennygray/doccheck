## Context

`AdminUsersPage.test.tsx` 的 `创建用户成功` 测试 L94:
```ts
const user = userEvent.setup();
await user.click(screen.getByTestId("create-user-btn"));
await user.type(screen.getByTestId("input-username"), "newuser");
await user.type(screen.getByTestId("input-password"), "Test1234");
await user.click(screen.getByText("确认创建"));
```

`userEvent.setup()` 默认 delay = `0`(ms),但在每个 keystroke 之间仍会 `await` 一个 `Promise.resolve()` + 微任务队列 flush,实质等效 ≥1 tick 的 setTimeout(0)。在 jsdom + antd + vitest workers 同时初始化的高负载环境下,每次 `user.type` 的 8-12 个 keystroke 累积延迟可从 isolated 下的 <100ms 放大到全量下的 >2-3s,叠加 4 次 `await user.*` → 总耗时 >5s → vitest 默认超时。

隔离跑 `npm test -- --run AdminUsersPage` 绿(4 tests in 5.11s,单个测试 ~1.3s)。
全量 `npm test -- --run` 失败(环境启动 286s 后单测 >5s)—— 不是测试逻辑错。

## Goals / Non-Goals

**Goals:**
1. `AdminUsersPage.test.tsx::创建用户成功` 在全量跑下稳定绿
2. 不改测试语义(断言 / mock / 交互顺序),只改 timing 行为
3. 加 minimal spec 契约,防未来其他前端交互测试引入同型 flaky
4. `cd frontend && npm test -- --run` 达到 **114/114 绿**

**Non-Goals:**
- **不**批改其他 `userEvent.setup()` 站点(grep 发现 DimensionRow / ReportPage / ReviewPanel 等用 userEvent 的测试目前全绿,无病例;防过度修复)
- **不**引入 `vi.useFakeTimers()`(结构改动大,可能引发其他 async await 交互问题)
- **不**改 vitest `testTimeout` 全局值(不精准,掩盖其他潜在 flaky)
- **不**改 AdminUsersPage 生产代码(组件工作正常,纯测试 infra 问题)

## Decisions

### D1 `userEvent.setup({ delay: null })` — userEvent v14 推荐路径

**选定**:`userEvent.setup({ delay: null })`。

**理由**:
- `delay: null` 是 userEvent v14 明确提供的 "跳过 keystroke 间 microtask tick" 模式
- 完全不改测试语义:`click` / `type` / `keyboard` 依旧走 React event handler / antd form validator,只是不再 wait microtask
- 不动 React 组件本体;不引入 `fireEvent`(fireEvent 缺 userEvent 的 ARIA-aware 行为)
- userEvent 官方推荐:无动画 UI 测试加 `delay: null`,动画 UI 测试配合 `vi.useFakeTimers` + `vi.advanceTimersByTime`。本测试是普通 form 交互,无动画 → 前者足够

**备选 A**(已否):`test("...", async () => {...}, 15000)` 拉高 timeout
- ❌ 不治本(仍累积延迟,只是放宽上限);未来 suite 继续膨胀可能再超
- ❌ 掩盖真正的 flaky 根因

**备选 B**(已否):`vi.useFakeTimers()` + `vi.runAllTimersAsync()`
- ❌ 可能影响 `await api.createUser` 等真实 async 的 mock resolve 时机
- ❌ 本测试无定时器交互,引入 fake timers 是过度设计

**备选 C**(已否):替换 `userEvent` 为 `fireEvent`
- ❌ fireEvent 绕过 ARIA / 键盘导航 / antd Form 的 Enter 提交等交互细节
- ❌ 测试语义会漂移,和其他 userEvent-based 测试风格不一致

### D2 Fallback 不主动加 —— 观察 apply 结果决定

**选定**:apply 期先只加 `delay: null`,跑 3 次全量 suite 观察;全绿即收工。若仍见偶发(估计 <5% 概率),追加 test-level timeout 15000ms 兜底:
```ts
test("创建用户成功", async () => { ... }, 15000);
```

**理由**:fallback 是独立补丁,scope 小;主方案(D1)若充分解决则无需 fallback,避免加无用 noise。

### D3 Spec:新 ADDED Requirement 而非 MODIFY 既有

**选定**:在 `pipeline-error-handling` 下**新 ADDED** "前端交互测试 timing 契约",1 Requirement + 1 scenario。

**理由**:
- 既有 "测试基础设施鲁棒性契约"(wave2 加的)是后端 3 契约点(alembic / run_isolated / engine except);前端 timing 独立主题,MODIFY 会冲淡焦点
- ADDED Requirement 精准、独立,命名清晰(题目锁意图)
- 单 scenario 不过度:只锁 "userEvent-based 前端交互测试 MUST delay: null 或 test-level timeout ≥15s",不规定 timeout 数值 / mock 行为等 implementation detail

**备选 A**(已否):MODIFY 既有 "测试基础设施鲁棒性契约",加第 4 scenario
- ❌ 主题不一致(后端 infra vs 前端 timing),且 MODIFY 必须 copy 完整 Requirement 内容负担重

### D4 scope 锁死 — 不批量改其他 userEvent 站点

**选定**:只改 `AdminUsersPage.test.tsx` 一处。其他 `userEvent.setup()` 站点暂不 touch。

**理由**:
- 无病例 / 无失败症状的站点主动改 = 过度修复(memory 禁忌)
- 若未来同型 flaky 在其他测试复现,单独处理,逐个评估
- spec 的 ADDED Requirement 为**未来新测试**提供契约约束(不强制批改历史)

## Risks / Trade-offs

- **[R1]** `delay: null` 在未来版本 userEvent API 变动下失效 → **Mitigation**:userEvent v14 API 稳定;若 v15+ 重命名,测试失败会以清晰报错暴露,非静默破坏
- **[R2]** `delay: null` 可能在极高负载 CI 下仍偶发 flaky → **Mitigation**:fallback 路径(test-level 15s timeout)已预留,apply 期观察决定
- **[R3]** 其他 `userEvent` 站点将来也出同问题 → **Mitigation**:spec 契约为新测试提供约束;历史站点靠 CI 观察逐一补修,不 preemptive 改

## Migration Plan

零迁移:
- 无 DB / API / 前端 route / 产品行为变更
- 测试文件改动,回滚直接回滚 commit

## Open Questions

(无。D1-D4 全自决;fallback 是否加 apply 期实证决定。)
