## ADDED Requirements

### Requirement: 解析完成自动流转项目状态到 ready

当项目内所有投标人的 `parse_status` 均达到终态时，系统 SHALL 自动将 `project.status` 从 `draft` 或 `parsing` 更新为 `ready`。

终态集合：`identified`, `priced`, `price_partial`, `partial`, `identify_failed`, `price_failed`, `needs_password`, `failed`, `skipped`。

#### Scenario: 两个投标人依次完成解析
- **WHEN** 项目有 2 个投标人，第 1 个已 `identified`，第 2 个刚到达 `priced`
- **THEN** 系统检测到所有 bidder 均为终态，将 `project.status` 更新为 `ready`

#### Scenario: 投标人解析失败也触发聚合
- **WHEN** 项目有 2 个投标人，1 个 `identified`，1 个 `identify_failed`
- **THEN** 两者均为终态，系统将 `project.status` 更新为 `ready`

#### Scenario: 部分投标人仍在解析中
- **WHEN** 项目有 3 个投标人，2 个已 `identified`，1 个仍为 `extracting`
- **THEN** 系统不更新 `project.status`，保持当前值

#### Scenario: 单个投标人的项目
- **WHEN** 项目仅有 1 个投标人且到达 `identified`
- **THEN** 系统将 `project.status` 更新为 `ready`

### Requirement: 上传触发解析时流转项目状态到 parsing

当投标人文件上传并开始解析时，系统 SHALL 将 `project.status` 从 `draft` 更新为 `parsing`。若已非 `draft` 则不变。

#### Scenario: 首次上传文件
- **WHEN** 项目状态为 `draft`，用户上传第一个投标人文件并触发解压
- **THEN** `project.status` 更新为 `parsing`

#### Scenario: 追加上传文件
- **WHEN** 项目状态已为 `parsing` 或 `ready`，用户追加上传新文件
- **THEN** `project.status` 保持不变（不回退）

### Requirement: 项目状态变更发送 SSE 事件

当 `project.status` 发生变更时，系统 SHALL 通过 progress_broker 发送 `project_status_changed` 事件。

#### Scenario: 状态流转到 ready 时发送事件
- **WHEN** 所有 bidder 到达终态，`project.status` 从 `parsing` 更新为 `ready`
- **THEN** SSE 事件流发送 `project_status_changed` 事件，payload 包含 `{"new_status": "ready"}`

### Requirement: 并发安全

多个投标人同时完成解析时，系统 SHALL 保证 `project.status` 仅被更新一次，不产生重复更新或数据竞争。

#### Scenario: 两个投标人同时到达终态
- **WHEN** 两个 bidder 的 `run_pipeline()` 几乎同时完成
- **THEN** 仅一个协程成功更新 `project.status`，另一个发现已更新后跳过
