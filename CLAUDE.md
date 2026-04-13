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
