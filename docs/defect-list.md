# 围标检测系统 — E2E 验收缺陷清单

> 测试日期: 2026-04-16 | 测试环境: 本地开发环境 (Windows 10 + PostgreSQL)
> 测试数据: 供方1技术标.docx + 供方2技术标.docx（仅技术标，无报价文件）
> LLM: 火山引擎 Ark / DeepSeek-V3.2 (ark-code-latest)

---

## 缺陷汇总

| 编号 | 严重度 | 模块 | 标题 | 状态 |
|------|--------|------|------|------|
| DEF-001 | **P1-严重** | 解析流水线 | 解析完成后项目状态不自动流转 | Open |
| DEF-002 | **P2-一般** | 检测引擎 | LLM 综合研判未被调用（降级结论） | Open |
| DEF-003 | **P2-一般** | 管理后台 | 系统启动无自动 seed 管理员账号 | Open |
| DEF-004 | **P3-轻微** | 文本对比 | 对比视图仅返回 1 条 match，与检测证据不对齐 | Open |
| DEF-005 | **P3-轻微** | API | 部分 API 路径缺少尾部斜杠导致 307 重定向 | Open |

---

## 缺陷详情

### DEF-001 [P1-严重] 解析完成后项目状态不自动流转

**现象**：上传文件并完成解析后（所有投标人达到 `identified` / `priced` 终态），`project.status` 仍停留在 `draft`，用户无法点击"开始检测"（API 返回 400: "项目未就绪"）。

**复现步骤**：
1. 创建项目 → 添加 2 个投标人 → 上传压缩包
2. 等待解析完成（两家均为 `identified`）
3. 调用 `POST /api/projects/{id}/analysis/start`
4. 返回 `{"detail":"项目未就绪"}`

**根因**：解析流水线（`run_pipeline()`）完成后仅更新 `bidder.parse_status`，没有检查"所有投标人是否都已完成"并将 `project.status` 从 `draft` 流转到 `ready`。

**代码位置**：
- 缺失逻辑应在 `backend/app/services/parser/pipeline/run_pipeline.py` 的 pipeline 完成回调处
- 检测启动校验在 `backend/app/api/routes/analysis.py:104`（`_PROJECT_START_ALLOWED = {"ready", "completed", "extracted"}`）

**预期行为**：
- 上传文件时：`draft` → `parsing`
- 所有投标人解析完成时：`parsing` → `ready`
- 同时发送 SSE 事件 `project_status_changed` 通知前端

**临时绕过**：手动 SQL `UPDATE projects SET status='ready' WHERE id=?`

---

### DEF-002 [P2-一般] LLM 综合研判未被调用

**现象**：检测完成后报告的 `llm_conclusion` 为降级模板文本（"AI 综合研判暂不可用,以下为规则公式结论..."），未调用真实 LLM 进行 L-9 综合研判。

**实际结论**：`AI 综合研判暂不可用,以下为规则公式结论:本项目加权总分 3.25 分,风险等级 low(低)。维度最高分:text_similarity 21.68、section_similarity 9.95。`

**可能原因**（按可能性排序）：
1. `LLM_JUDGE_ENABLED` 环境变量未设置或默认为 `false`
2. LLM judge 调用 Ark API 时因 `max_tokens` 参数触发 InternalServiceError（Ark coding 端点不支持 `max_tokens`）
3. LLM judge 调用超时（默认 30s，Ark 响应可能较慢）

**代码位置**：
- 研判入口：`backend/app/services/detect/judge.py:judge_and_create_report()`
- LLM 调用：`backend/app/services/detect/judge_llm.py:call_llm_judge()`
- 配置：`LLM_JUDGE_ENABLED` / `LLM_JUDGE_TIMEOUT_S` 环境变量

**排查建议**：
1. 确认 `.env` 中是否有 `LLM_JUDGE_ENABLED=true`
2. 检查后端日志中 judge 阶段的 LLM 调用是否报错
3. 确认 `call_llm_judge()` 是否传了 `max_tokens` 参数

---

### DEF-003 [P2-一般] 系统启动无自动 seed 管理员账号

**现象**：后端服务启动后 `users` 表为空，无法登录系统。需要手动通过脚本或 SQL 创建管理员账号。

**复现步骤**：
1. 全新数据库（已跑 migration）
2. 启动后端服务
3. 尝试登录 → 401 用户名或密码错误

**根因**：`config.py` 中定义了 `auth_seed_admin_username` / `auth_seed_admin_password`，但 `main.py` 的 `lifespan()` 中没有调用 seed 逻辑。

**代码位置**：
- 配置定义：`backend/app/core/config.py:31-32`
- 启动生命周期：`backend/app/main.py:31`（`lifespan` 函数，缺少 seed 调用）

**预期行为**：首次启动时检测 users 表是否为空，若空则自动创建 seed admin 账号（`must_change_password=True`）。

---

### DEF-004 [P3-轻微] 对比视图 match 数量与检测证据不完全对齐

**现象**：检测维度 `text_similarity` 得分 21.68，evidence 中有多个 sim>0.7 的段落对，但文本对比视图 (`GET /compare/text`) 仅返回 1 条 match。

**分析**：
- 对比视图的 `matches` 来自 `PairComparison.evidence_json["samples"]`
- `samples` 数量受 `_SAMPLES_LIMIT` 限制
- 实际返回了 236 vs 457 个段落（left/right），说明段落提取正常
- match 数偏少可能是 `samples` 只保存了 top-N 高相似对

**代码位置**：
- 对比逻辑：`backend/app/api/routes/compare.py:81-214`
- Sample 限制：`backend/app/services/detect/agents/text_sim_impl/aggregator.py:98`

**影响**：用户在对比视图中看到的相似段落偏少，不能完整展示检测发现的所有相似内容。

**建议**：对比视图可独立计算段落相似度（不仅依赖 evidence 中的 samples），或增大 `_SAMPLES_LIMIT`。

---

### DEF-005 [P3-轻微] API 路径尾部斜杠导致 307 重定向

**现象**：部分 API 路径不带尾部 `/` 时返回 307 Temporary Redirect，客户端需 follow redirect 才能正常请求。

**复现**：
```
POST /api/projects  → 307 → /api/projects/
```

**影响**：
- httpx 等客户端默认不跟随 redirect（需显式 `follow_redirects=True`）
- 增加一次不必要的网络往返
- 前端 fetch 可能需要额外处理

**建议**：在 FastAPI 路由定义中统一 `redirect_slashes=False`，或确保路由定义与客户端调用风格一致。

---

## 非缺陷项（已排除）

| 现象 | 结论 |
|------|------|
| API 返回的中文显示乱码 | **非缺陷**。DB 存储正确（UTF-8），乱码仅因 Windows cmd 终端编码（GBK）导致；前端/浏览器显示正常 |
| price 相关维度全部 0 分 | **符合预期**。测试数据仅有 .docx 技术标，无 .xlsx 报价文件，price_consistency / price_anomaly 被正确 skip |
| style 维度 0 分 | **符合预期**。仅 2 家投标人且文本量有限，style agent 预检不通过被 skip |

---

> 缺陷确认人: __________ 日期: __________
