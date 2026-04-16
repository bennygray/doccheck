## 1. 核心实现

- [x] 1.1 [impl] 新建 `backend/app/services/parser/pipeline/project_status_sync.py`，实现 `try_transition_project_ready(project_id)` 函数：查询同项目所有 bidder 的 parse_status，若均为终态则用 `SELECT ... FOR UPDATE` 加锁更新 `project.status` 为 `ready`，并通过 progress_broker 发送 `project_status_changed` 事件
- [x] 1.2 [impl] 在 `run_pipeline.py` 的所有 bidder 终态出口（identified / priced / price_partial / partial / identify_failed / price_failed）后调用 `try_transition_project_ready(project_id)`
- [x] 1.3 [impl] 在 `extract_archive()` 入口处（或上传触发解析处），若 `project.status == 'draft'` 则原子更新为 `parsing`

## 2. 单元测试

- [x] 2.1 [L1] 测试 `try_transition_project_ready`：所有 bidder 终态 → project.status 变为 ready
- [x] 2.2 [L1] 测试 `try_transition_project_ready`：部分 bidder 仍在解析 → project.status 不变
- [x] 2.3 [L1] 测试 `try_transition_project_ready`：含失败 bidder（identify_failed）→ 仍触发 ready
- [x] 2.4 [L1] 测试 `try_transition_project_ready`：单个 bidder 项目 → 终态即触发 ready
- [x] 2.5 [L1] 测试上传文件时 draft → parsing 流转

## 3. E2E 测试

- [x] 3.1 [L2] E2E：创建项目 → 上传 2 个投标人文件 → 等待解析完成 → 验证 project.status == ready → 启动检测成功

## 4. 全量测试

- [x] 4.1 跑 [L1][L2] 全部测试，全绿 (1034 passed in 107.86s)
