# C15 report-export L3 手工凭证占位(2026-04-16)

Docker Desktop kernel-lock 延续(C3~C14 L3 全部阻塞中),本次 L3 手工凭证同样降级为占位 + 文字说明,待 kernel-lock 解除后补截图。

## 待补截图清单(3 张,覆盖 3 条手工验证路径)

### 1. 导出 Word 下载 smoke

**步骤**
1. `docker compose up -d && npm run dev`
2. 登录 reviewer 账号 → 进一个已完成检测的项目 → 报告页
3. 点击右上角"导出 Word"按钮
4. 观察进度条(SSE export_progress 事件驱动)从 0 走到 1
5. 完成后浏览器自动触发一次 .docx 下载
6. 截图:① 进度条中间态 ② 下载完成后的"已生成"绿色提示 ③ 下载的 .docx 内容首页

**预期**
- 进度条显示 "渲染模板" → "写入文件" → "完成" 阶段文字
- 下载文件 filename 格式:`report_{pid}_v{version}_{job_id}.docx`
- Word 内容包含:项目名 / 总分 / 风险等级 / 11 维度明细 / top 5 pair / 复核段(若已复核)

### 2. 整报告级复核提交

**步骤**
1. 同上进报告页
2. 滚动到 "人工复核" 区(ReviewPanel 组件)
3. 选择 "确认围标" + 填写"证据充分"评论
4. 点击 "提交复核"
5. 页面刷新 → 复核区切成只读摘要态
6. 截图:① 复核前表单 ② 提交后只读摘要 ③ 检测日志页新增 audit_log `review.report_confirmed` 条目

**预期**
- 复核成功后 AR.total_score / risk_level 保持不变(D11 约束)
- audit_log 记 before_json={status:null,comment:null}, after_json={status:"confirmed",comment:"证据充分"}
- 只读摘要显示"结论:确认围标 / 评论:证据充分 / 时间 + user#id"

### 3. 降级 banner(LLM 不可用)展示

**步骤**
1. 后端 env `LLM_JUDGE_ENABLED=false` 重启
2. 跑一次完整检测 → 进报告页
3. 观察顶部黄色 banner 显示 "AI 综合研判暂不可用..." 前缀文案
4. 截图:报告页顶部(含 banner)

**预期**
- `<div data-testid="llm-fallback-banner">` 渲染可见
- banner 文案以 C14 固定前缀 `"AI 综合研判暂不可用"` 开头
- total_score / 维度得分正常展示(banner 不阻塞主体内容)

## 当前状态(2026-04-16)

- **Docker kernel-lock 未解除**(与 C3~C14 同)— Playwright 无法跑
- L1 单元 + 组件测试已全面覆盖:
  - **后端 L1 25 用例**(test_alembic_0008 10 + test_audit_service 5 + test_export_generator 10)
  - **前端 Vitest 73 用例**(含 C15 新增 ReviewPanel 3 / ExportButton 4 / ReportPage 降级 banner 2)
- L2 e2e 测试已覆盖全部关键路径:
  - `test_reviews_api.py` 10 用例(复核 + 维度级 + 权限 + 检测原值不变)
  - `test_report_views_api.py` 9 用例(总览 / dimensions / pairs / logs)
  - `test_exports_api.py` 6 用例(默认模板 / 用户模板 fallback / 渲染失败 / 过期 410 / 权限 404)

## L1 / L2 覆盖证明

- **后端 L1** 关键测试文件:
  - `backend/tests/unit/test_alembic_0008.py`:migration + 新模型 ORM(10 用例)
  - `backend/tests/unit/test_audit_service.py`:audit.log_action(5 用例,含 DB 失败吞异常)
  - `backend/tests/unit/test_export_generator.py`:render_context 装配 / 铁证 top-k / render_to_file / 模板回退(10 用例)

- **前端 Vitest** 关键测试文件:
  - `frontend/src/pages/reports/__tests__/ReportPage.test.tsx`:降级 banner 识别 + 5 既有
  - `frontend/src/components/reports/__tests__/ReviewPanel.test.tsx`:表单校验 + 提交 + 修改(3 用例)
  - `frontend/src/components/reports/__tests__/ExportButton.test.tsx`:状态机 idle→running→done/failed(4 用例)

- **后端 L2** 关键测试文件:
  - `backend/tests/e2e/test_reviews_api.py` 10 用例
  - `backend/tests/e2e/test_report_views_api.py` 9 用例
  - `backend/tests/e2e/test_exports_api.py` 6 用例

## 手工验证清单(kernel-lock 解除后执行)

- [ ] 按上述步骤 1 截图并保存为 `screenshot-01-export-flow.png`
- [ ] 按步骤 2 截图(3 张)保存为 `screenshot-02a-review-form.png` / `screenshot-02b-review-readonly.png` / `screenshot-02c-audit-log.png`
- [ ] 按步骤 3 截图保存为 `screenshot-03-fallback-banner.png`
- [ ] 全部截图补齐后移除本 README 的"占位"标识
