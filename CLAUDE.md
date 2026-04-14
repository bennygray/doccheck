# 围标检测系统 (DocumentCheck)

## 项目概述
投标文件围标/串标行为检测系统，通过分析投标文件的文本相似度、元数据、报价模式和投标人关联关系来识别围标风险。

## 技术栈
- **后端**: Python 3.12+ / FastAPI / SQLAlchemy / Alembic
- **前端**: React + TypeScript / Vite
- **数据库**: PostgreSQL
- **依赖管理**: uv (后端) / npm (前端)

## 项目结构
```
backend/          Python FastAPI 后端
  app/
    api/routes/   API 路由
    core/         配置、安全
    models/       数据库模型
    schemas/      Pydantic 数据模型
    services/
      parser/     文档解析 (DOCX/XLSX)
      analyzer/   分析引擎 (相似度/元数据/报价)
      detector/   围标检测规则引擎
    db/           数据库连接
  tests/          测试
frontend/         React 前端
  src/
    components/   UI 组件
    pages/        页面
    services/     API 调用
    hooks/        自定义 hooks
    types/        TypeScript 类型
```

## 开发命令
```bash
# 后端
cd backend
uv sync
uvicorn app.main:app --reload

# 前端
cd frontend
npm install
npm run dev

# Docker 一键启动
docker compose up
```

## 代码规范
- Python: ruff (line-length=88)
- TypeScript: eslint + prettier
- 提交信息用中文描述

## 测试标准(Testing Standard)

三层分层测试,每个 change 归档前必须通过对应层级测试。

### L1 单元+组件测试
- 前端: Vitest + React Testing Library
- 后端: pytest
- 位置: `frontend/src/**/*.test.ts(x)`、`backend/tests/unit/`
- 覆盖: 纯函数、组件渲染、业务规则
- 命令: `npm test` / `pytest backend/tests/unit/`

### L2 API 级 E2E 测试
- 工具: pytest + FastAPI TestClient + httpx
- 位置: `backend/tests/e2e/`
- 覆盖: 后端全链路(登录→建项目→上传→解析→检测→报告),不走 UI
- LLM 默认 mock(统一 fixture)
- 命令: `pytest backend/tests/e2e/`

### L3 UI 级 E2E 测试
- 工具: Playwright + TypeScript
- 位置: 项目根 `e2e/`(独立于 frontend)
- baseURL: 默认 `http://localhost:5173`(Vite dev server);CI/联调用 docker compose 产物
- fixtures: `e2e/fixtures/`;种子数据脚本 `e2e/seed.ts`
- 覆盖: 仅 UI 独有场景(SSE 实时进度、文件对比视图、Word 下载交互)
- 命令: `npm run e2e`(项目根目录)

### 与 change 的对接
- change 的 tasks.md 里每条任务必须带标签: `[impl]` / `[L1]` / `[L2]` / `[L3]` / `[manual]`
- tasks.md 末尾必须含一条总汇任务: `[ ] 跑 [L1][L2][L3] 全部测试,全绿`
- change 归档前对应层级测试必须全绿

### 各层 flaky 兜底
- L1: 必须稳,不允许跳过
- L2: flaky 隔离到独立 suite,标 `@flaky`,72h 内修复
- L3: flaky 允许降级为手工+截图凭证(与 `docs/execution-plan.md` §2.3 过程兜底第 3 条对齐)

### LLM mock 约定
- 后端: `backend/tests/fixtures/llm_mock.py`(单一入口,8 个 LLM 调用点共享)
- 前端: Playwright 用 `page.route` 拦截 LLM 相关 API
- 真 LLM 调用标 `[manual]`,不进自动化

### 约定目录
- L3 artifacts(截图/录屏): `e2e/artifacts/`(加入 .gitignore)
- 种子数据脚本: `e2e/seed.ts`
- 测试 fixtures: `e2e/fixtures/`、`backend/tests/fixtures/`

### OpenSpec 集成(覆盖默认 skill 行为)

本项目使用 openspec-propose / openspec-apply-change / openspec-archive-change,以下约定**优先于** skill 默认步骤:

**propose 阶段(生成 tasks.md 时)**
- 每条任务必须带标签: `[impl]` / `[L1]` / `[L2]` / `[L3]` / `[manual]` 之一
- tasks.md 末尾必须含总汇任务: `[ ] 跑 [L1][L2][L3] 全部测试,全绿`
- 不能仅有 `[impl]` 任务;至少对应一层测试。孤立改文档/配置的 change 例外,需在 proposal.md 说明

**apply-change 阶段(实施任务时)**
- `[L1]`/`[L2]` 任务: 运行对应命令,看到全绿输出后才标 `[x]`,失败则修至通过
- `[L3]` 任务: 运行 `npm run e2e`,全绿标 `[x]`;若 flaky → 降级为手工+截图,截图路径写入该任务条目作为凭证
- `[manual]` 任务: 人工执行,结果记录在该任务条目后

**archive-change 阶段(归档前)**
- 归档前必须校验: 所有 `[L1]`/`[L2]`/`[L3]` 任务均 `[x]`
- L3 降级为手工凭证的,凭证文件必须存在于 `e2e/artifacts/`
- 任一不满足 → 拒绝归档

(与 `docs/execution-plan.md` §2.3 过程兜底第 3 条对齐,实现同一约束的工具落地)

## 项目进度追踪

### Handoff 文件维护
- 位置: `docs/handoff.md`
- 作用: 跨会话/跨人接手的**现场视角**快照(与 `docs/execution-plan.md` §5 的路线图视角分工)
- 固定结构: 当前状态快照 / 本次 session 决策 / 待确认阻塞 / 下次开工建议 / 最近变更历史(最多 5 条)
- 更新时机:
  1. 每次 `openspec-archive-change` 成功后(**强制**,随 commit 一起提交)
  2. 每次用户确认重大决策后(方案变更、粒度调整、工具选型变化等)
  3. session 结束前(若有未持久化的讨论结论)

### archive 自动 commit(覆盖 openspec-archive-change 默认行为)
- archive-change 成功移动目录后,**必须**立即执行一次 `git commit`(此规则构成 Claude Code 主动 commit 的 durable 授权)
- commit 包含:
  1. archive 目录移动(`openspec/changes/<name>` → `openspec/changes/archive/YYYY-MM-DD-<name>`)
  2. 本次 change 实施的所有代码/配置/测试改动
  3. `docs/handoff.md` 的状态更新
- commit message 格式: `归档 change: <change-name>(M<n>)`
- commit 后**不 push**,push 由用户单独指示
- commit 前检查 `git status`,确认无 `.env` 等敏感文件被纳入;若发现 → 拒绝 commit 并提示用户处理

## graphify 知识图谱检索

项目已接入 graphify，图数据持久化在 `graphify-out/`(已 gitignore)。

### 何时查图（Claude 主动用）
回答下列类型问题前，**必须**先 `/graphify query "..."` 或 `/graphify path A B` 或 `/graphify explain X`，不得靠直接 grep/read 盲搜：
- 架构级 / 跨文件 / 跨层问题("X 怎么连到 Y"、"这个抽象在哪些地方被用到")
- 某个核心概念的影响面("动 BidDocument 模型会连带影响什么")
- 找重复实现 / 近义抽象("有没有类似 X 的 helper")

### 何时刷图（用户或 Claude 触发）
- **代码改动后**（纯 .py/.ts/.tsx 等）：`/graphify --watch` 后台监视 或 commit 时手工 `/graphify --update`；纯代码改动只跑 AST，免 LLM 免 token
- **文档/spec/截图改动后**：必须 `/graphify --update` 完整流水线(含 LLM 语义抽取)；这属于昂贵操作，执行前要先告知用户成本
- **重大里程碑归档后**（M1/M2... 结束）：完整 `/graphify --update` 一次，确保图与代码库同步

### 词义澄清（防止"刷新"被理解成"升级"）
用户说"刷图/刷新图"时默认 **轻量档**（只看现状或 AST-only）；说"重建/全量/完整 rebuild"才是 **完整档**（含 LLM）。不确定就问。
