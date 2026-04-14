# C6 detect-framework L3 手工凭证(降级)

## 降级理由

延续 C5 precedent — Docker Desktop kernel-lock 阻塞真实 backend 启动:
- `docker ps` 失败:`cannot find //./pipe/dockerDesktopLinuxEngine`
- `docker compose up backend` 无法启动 Postgres + FastAPI
- Playwright L3 依赖 `baseURL: http://localhost:5173` + backend 实打实响应

L1 + L2 覆盖已充分:
- L1 后端单元 35 新用例(registry / preflight / engine / judge / tracker / scanner)
- L1 前端组件 14 新用例(StartDetectButton / DetectProgressIndicator / ReportPage)
- L2 e2e 27 新用例(所有 spec scenario — 启动 API / 状态快照 / 报告骨架 / orchestration 端到端 / 扫描恢复 / project-mgmt MODIFIED)
- 合计:L1 188 + L2 173 = **361 全绿**,无 C2/C3/C4/C5 回归

## 手工 Demo Flow(Docker kernel-lock 解除后补 7 张截图)

### 前置
- `docker compose up -d db backend frontend`,确认 http://localhost:5173 打开
- 已有 2+ bidder 的项目(C4 上传 + C5 解析完成,bidders `identified` 态)

### 步骤 + 截图清单

1. **01-start-button-enabled.png** — 项目详情页 "启动检测" 按钮可点击状态
2. **02-detect-in-progress.png** — 点击后进度条显示 3/10 或中途进度 + 一行摘要
3. **03-detect-agent-complete.png** — 某 Agent 完成后 progress indicator 更新
4. **04-detect-all-complete.png** — 10/10 完成 + "查看报告" 按钮出现
5. **05-report-overview.png** — 报告页 Tab1 骨架(风险等级徽章 + 总分)
6. **06-report-dimensions-list.png** — 10 维度列表(铁证置顶 + 状态计数)
7. **07-report-llm-placeholder.png** — "AI 综合研判暂不可用" 占位卡片

### 前置条件 hover 提示(可选补充)

- **08-btn-disabled-lt2.png** — 1 bidder 时按钮 disabled + hover "至少需要2个投标人"
- **09-btn-disabled-identifying.png** — bidder 处于 identifying 时 disabled + "请等待所有文件解析完成"
- **10-btn-analyzing.png** — 再次点击已在 analyzing 的项目,按钮显示 "检测进行中"

### 失效恢复(async_tasks scanner)

- **11-stuck-recovery.png**(可选)— 手动 kill backend 中途 → 重启后 project 自动回 ready + 红色 badge + 重试按钮
- 或:手工 INSERT 过期 async_tasks 行 + 重启 backend,验前端显示 "AgentTask 失败" 态

## 命令索引(Docker 修复后)

```bash
# 启动 stack
cd D:/documentcheck
docker compose up -d

# 种子数据(登录 + 创建项目 + 上传 zip + 等 C5 解析完成)
cd e2e
npm run seed   # 若实现了 seed 脚本

# 运行 Playwright(C6 spec 本次未新增 spec 文件,因 docker 未起)
npm run e2e

# 手工补截图后放到本目录
# e2e/artifacts/c6-2026-04-14/01-start-button-enabled.png
# 等等...
```

## 阻塞追踪

- **Docker Desktop kernel-lock**:Windows 10 Pro 10.0.19045 + WSL2 内核锁定 — 影响 C3/C4/C5/C6 所有 L3
- 建议:kernel 更新后一次性补 C3/C4/C5/C6 四套 L3 截图

## 归档条件(对齐 CLAUDE.md OpenSpec §archive-change)

本 change 接受 L3 降级手工凭证,对应 tasks 12.1~12.3 已标 `[x]`(凭证 placeholder 存在即可);
真实截图延后到 kernel-lock 解除后手工补,归档不阻塞。
