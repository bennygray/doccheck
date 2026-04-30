## ADDED Requirements

### Requirement: 项目详情页招标文件区块

`ProjectDetailPage` SHALL 新增"招标文件"区块,在投标人列表之上、项目基本信息之下。

区块内容 MUST 含:
- 上传按钮(复用 `AddBidderDialog` 的 drag-drop + 文件校验模式)
- 已上传招标文件列表(file_name + parse_status Tag + 删除按钮)
- 基线状态 Badge(L1 蓝/L2 琥珀/L3 中性灰),复用 `tokens.ts` 既有色板,**不新增色值**

招标文件区块 MUST 受前端 feature flag `VITE_TENDER_BASELINE_ENABLED` 控制:flag=false 时区块隐藏(详情页布局回退到 change 前)。

#### Scenario: feature flag 关闭时区块隐藏

- **WHEN** `VITE_TENDER_BASELINE_ENABLED=false`,用户访问项目详情页
- **THEN** 招标文件区块 MUST NOT 渲染,布局与 change 前完全一致

#### Scenario: feature flag 开启 + 已传 tender

- **WHEN** flag=true,project 已传 1 份 tender (extracted)
- **THEN** 区块显示文件名 + Tag "解析完成" + 基线状态 Badge "招标文件已就绪 L1"(蓝色)

#### Scenario: feature flag 开启 + 未传 tender + 投标方 ≥3

- **WHEN** flag=true,project 无 tender,投标方 4 家
- **THEN** 区块显示空状态 + 基线状态 Badge "共识基线 L2"(琥珀色)

#### Scenario: feature flag 开启 + 未传 tender + 投标方 ≤2

- **WHEN** flag=true,project 无 tender,投标方 2 家
- **THEN** 区块显示空状态 + 基线状态 Badge "警示模式 L3"(中性灰) + Alert 警示条"建议补传招标文件以提升检测精度"

---

### Requirement: 启动检测前预检查 dialog

`StartDetectButton` SHALL 在启动检测前检查 baseline 可用性。

未传 tender + 用户未关闭"不再提醒" 时,系统 MUST 弹 Alert warning Dialog,内容:
- 标题:"未上传招标文件"
- 正文:"模板段识别精度可能受影响。建议补传招标文件后再启动检测。"
- 按钮:"取消" / "仍要启动" / "去补传"
- 底部 checkbox:"本项目不再提醒"(localStorage 持久化,key=`tender_baseline_warning_dismissed_<project_id>`)

已传 tender 或用户已关闭提醒时,SHALL 直接启动检测,不弹 Dialog。

localStorage key 命名 MUST 用 `tender_baseline_warning_dismissed_<project_id>` 形式;value MUST 存 JSON `{"value": true, "ts": <Date.now()>}`(plain `'true'` 不行,LRU 裁剪需要时间戳);**为避免 localStorage 5MB 配额慢慢被吃光**,实现时 MUST:① 仅在用户主动勾选"不再提醒"时写入 ② 项目软删时清理对应 key ③ 单次 localStorage 写入前扫描 key 总数,> 1000 时按 `ts` 升序清理最旧 200 条(LRU 裁剪)。

Dialog MUST 受 feature flag `VITE_TENDER_BASELINE_ENABLED` 控制:flag=false 时跳过检查直接启动。

#### Scenario: 未传 tender 启动检测弹 Dialog

- **WHEN** flag=true,project 无 tender,用户首次点"启动检测"
- **THEN** 弹 Dialog,默认按钮"去补传"高亮

#### Scenario: 用户勾选"不再提醒"

- **WHEN** 用户在 Dialog 勾选"不再提醒"并点"仍要启动"
- **THEN** localStorage 写入 `tender_baseline_warning_dismissed_<pid>=true`,启动检测

#### Scenario: 已勾选"不再提醒"二次启动

- **WHEN** 同一项目第二次启动检测,localStorage 已有 dismiss 标记
- **THEN** SHALL 直接启动,不弹 Dialog

#### Scenario: feature flag 关闭跳过预检查

- **WHEN** flag=false 用户启动检测
- **THEN** SHALL 直接启动,不弹 Dialog(行为与 change 前一致)

---

### Requirement: 补传 tender 后重跑 dialog

补传招标文件成功(TenderDocument 转 extracted)后,**且** project 当前已有至少 1 份 AnalysisReport(`completed` 态)时,系统 SHALL 弹 info Dialog:
- 标题:"招标文件已就绪"
- 正文:"是否立即用新基线重新检测?新检测将作为 v_n+1 保留,历史 v_n 仍可访问。"
- 按钮:"否" / "是,立即重新检测"

用户选"是" → 调用 `POST /api/projects/{pid}/analysis`(现有端点,自动 max(version)+1)启动新检测。

用户选"否" → UI 在该 project 老 version 报告头部加 Stale Badge "v_n 数据未含本次招标文件,可能存在误报"。

Dialog MUST 受 feature flag 控制。

#### Scenario: 补传 tender 后弹重跑 dialog

- **WHEN** flag=true,project 已有 v=1 completed 报告,用户补传 tender 成功
- **THEN** 弹 info Dialog 询问"立即重新检测"

#### Scenario: 用户选"是"触发新版本检测

- **WHEN** 用户在 Dialog 点"是,立即重新检测"
- **THEN** 系统 POST /api/projects/{pid}/analysis,创建 v=2 检测,跳转检测进度页

#### Scenario: 用户选"否"老版本加 Stale Badge

- **WHEN** 用户点"否"
- **THEN** v=1 报告头部 SHALL 显示 Stale Badge,文案"未含 tender 基线"

#### Scenario: project 无历史 report 不弹 dialog

- **WHEN** flag=true,project 从未启动过检测,用户上传 tender
- **THEN** SHALL NOT 弹重跑 Dialog(无 stale 数据可警示)
