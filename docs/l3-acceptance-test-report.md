# L3 验收测试报告

> 测试日期: 2026-04-16 | 测试环境: 本地 3 进程 (PostgreSQL + uvicorn:8001 + Vite:5173)
> 测试工具: Playwright + Chromium | 总耗时: ~1.5 分钟

---

## 1. 测试总览

| 测试套件 | 总数 | 通过 | 失败 | 通过率 |
|----------|------|------|------|--------|
| acceptance-pipeline.spec.ts | 8 | 5 | 1+2跳过 | 62.5% |
| admin-management.spec.ts | 3 | 3 | 0 | 100% |
| **合计** | **11** | **8** | **3** | **72.7%** |

注: acceptance-pipeline 使用 `describe.serial`，test 5 失败后 test 6/7/8 被跳过。通过补测脚本独立验证了 test 6/7/8，实际结果: test 6 失败、test 7 通过、test 8 通过。

---

## 2. 逐项测试结果

### acceptance-pipeline.spec.ts（主链路验收）

| # | 测试名称 | 结果 | 耗时 | 备注 |
|---|---------|------|------|------|
| 1 | 创建项目并上传两个投标人 | ✅ 通过 | 1.2s | |
| 2 | 等待解析完成 | ✅ 通过 | 15.9s | 两个 bidder 均到达 priced 终态 |
| 3 | 启动检测并等待完成 | ✅ 通过 | 38.9s | 需要兜底脚本触发状态流转，见 BUG-1 |
| 4 | 报告页面渲染正确 | ✅ 通过 | 1.0s | 总分、风险等级、维度列表、导航链接均正常 |
| 5 | 对比视图三种类型 | ❌ 失败 | 10.9s | 文本对比页显示"无可对比的同类文档"，见 BUG-2 |
| 6 | 触发导出 | ❌ 失败 | 31.0s | 导出按钮点击后 30s 内无状态变化，见 BUG-3 |
| 7 | 人工复核 | ✅ 通过 | 1.1s | |
| 8 | 审计日志 | ✅ 通过 | 0.98s | |

### admin-management.spec.ts（管理后台）

| # | 测试名称 | 结果 | 耗时 | 备注 |
|---|---------|------|------|------|
| 9 | 用户管理 — 列表+创建+禁用 | ✅ 通过 | 1.5s | |
| 10 | 规则配置 — 查看+修改+恢复默认 | ✅ 通过 | 1.2s | 控制台有 React warning，见 WARN-1 |
| 11 | 非 admin 角色无法访问管理后台 | ✅ 通过 | 1.8s | |

---

## 3. 发现的缺陷

### BUG-1: 项目状态自动流转失败（后端）

- **严重度**: 高
- **现象**: 解析 pipeline 完成后（bidder 到达 priced/identified 终态），`project.status` 停留在 `draft`，不自动流转到 `ready`。导致"启动检测"按钮报错"项目未就绪"。
- **根因分析**: `run_pipeline.py` 在 6 个出口调用 `try_transition_project_ready(project_id)`，该函数在独立 CLI 调用时正常工作，但在 uvicorn 异步事件循环中执行时静默失败。怀疑是 SQLAlchemy async session 在 pipeline 的 `asyncio.create_task` 上下文中与主 session 存在事务隔离或锁竞争。
- **影响范围**: 每次上传解析后都需要手动干预才能启动检测。
- **测试中的兜底**: 用 `execSync` 调后端脚本手动触发 `try_transition_project_ready`。
- **涉及文件**:
  - `backend/app/services/parser/pipeline/run_pipeline.py`（调用点）
  - `backend/app/services/parser/pipeline/project_status_sync.py`（实现）

### BUG-2: 文本对比页面无数据（后端 + 配置）

- **严重度**: 高
- **现象**: 文本对比页面 `/compare/text?bidder_a=X&bidder_b=Y` 显示"无可对比的同类文档"，左右面板不渲染。
- **根因分析**: 两层原因叠加——
  1. **text_similarity agent 在检测时被 skip**: 虽然两个投标人的 `技术方案.docx` 都被正确分类为 `technical`，但 `choose_shared_role()` 在 engine session 上下文中返回空列表（独立 session 调用正常），与 BUG-1 同源的 session 隔离问题。
  2. **MIN_DOC_CHARS 阈值过高**: 默认 500 字符，但测试 fixture 的技术方案文档只有 ~350 字符。即使 session 问题修复后，当前 fixture 仍会因字数不足被 skip。实际投标文件中也可能存在不到 500 字的文档。
- **影响范围**: 文本对比和章节对比两个维度完全无效。对比视图的核心价值受损。
- **建议修复**:
  1. 修复 engine session 的事务隔离问题（与 BUG-1 同源）
  2. 将 `TEXT_SIM_MIN_DOC_CHARS` 从 500 降至 300
- **涉及文件**:
  - `backend/app/services/detect/agents/text_sim_impl/config.py`（阈值 500→300）
  - `backend/app/services/detect/agents/text_similarity.py`（preflight 调用 choose_shared_role）
  - `backend/app/services/detect/engine.py`（session 传递）

### BUG-3: Word 导出无响应（后端）

- **严重度**: 中
- **现象**: 点击"导出 Word"按钮后，30 秒内按钮状态无任何变化（不显示进度条、不显示成功/失败），保持在 idle 状态。
- **根因分析**: 导出按钮通过 `api.startExport()` POST 请求触发异步导出任务，然后监听 SSE `export_progress` 事件。可能的原因:
  1. 导出 API 返回了错误但前端未处理（按钮没变化说明请求可能失败了）
  2. 异步导出任务启动了但 SSE 事件未推送
  3. Word 模板渲染失败但错误被吞掉
- **影响范围**: 报告无法导出为 Word 文件。
- **涉及文件**:
  - `backend/app/api/routes/exports.py`
  - `backend/app/services/export/`
  - `frontend/src/components/reports/ExportButton.tsx`

### WARN-1: React 控制台警告（前端）

- **严重度**: 低
- **现象**: 规则配置页面加载时控制台报错: `value prop on input should not be null. Consider using an empty string.`
- **根因分析**: AdminRulesPage 中某些 input 的 value 初始化为 null 而不是空字符串。
- **影响范围**: 不影响功能，但可能导致受控/非受控组件切换的边界问题。
- **涉及文件**: `frontend/src/pages/admin/AdminRulesPage.tsx`

---

## 4. 环境相关问题

### ENV-1: 端口 8000 被占用

- CLodopPrint32.exe（打印服务）占用 8000 端口且有守护进程自动重启，杀不掉。
- 当前 workaround: 后端改用 8001 端口，Vite 代理同步调整。
- **涉及文件**: `frontend/vite.config.ts`（已修改为读取 `BACKEND_PORT` 环境变量，默认 8001）

---

## 5. 修复优先级建议

| 优先级 | 缺陷 | 建议 |
|--------|------|------|
| P0 | BUG-1 项目状态流转 | 排查 engine session 事务隔离，确保 pipeline 完成后 project.status 自动变为 ready |
| P0 | BUG-2 文本对比无数据 | 与 BUG-1 同源；同时将 MIN_DOC_CHARS 从 500 降至 300 |
| P1 | BUG-3 导出无响应 | 排查导出 API 和 SSE 推送链路 |
| P2 | WARN-1 React 警告 | input value null → "" |

---

## 6. 测试文件清单

本轮新增文件（测试代码 + fixture）:

| 文件 | 说明 |
|------|------|
| `e2e/fixtures/gen_test_bidders.py` | 生成测试用 ZIP 的 Python 脚本 |
| `e2e/fixtures/bidder-a.zip` | 投标人 A 测试数据（技术方案+投标函+报价清单） |
| `e2e/fixtures/bidder-b.zip` | 投标人 B 测试数据（与 A 共享 6 段文本） |
| `e2e/tests/acceptance-pipeline.spec.ts` | 主链路验收 8 个测试 |
| `e2e/tests/admin-management.spec.ts` | 管理后台验收 3 个测试 |

修改文件:

| 文件 | 说明 |
|------|------|
| `frontend/vite.config.ts` | 后端端口改为环境变量（兼容 8001） |
