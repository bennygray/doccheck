# Backend

围标检测系统后端 — Python 3.12 + FastAPI + SQLAlchemy(async)+ PostgreSQL。

## 依赖准备

```bash
cd backend
uv sync               # 装运行时依赖
uv sync --extra dev   # 加测试 / lint 工具
```

### C4 file-upload 系统依赖

C4 引入了压缩包解压链路,对宿主系统有额外要求:

- **libmagic**(`python-magic` 后端,做扩展名+魔数双校验)
  - Windows:`pyproject.toml` 已 pin `python-magic-bin`,自带 libmagic,无需手动装
  - Linux:`apt-get install libmagic1`
  - macOS:`brew install libmagic`
- **unrar**(`rarfile` 解 RAR 用;可选,缺失时 RAR 测试自动 skip)
  - Linux:`apt-get install unrar`
  - macOS:`brew install rar`
  - Windows:从 https://www.rarlab.com/ 下载 unrar.exe 并放到 PATH
- 7Z / ZIP 由 `py7zr` / 标准库 `zipfile` 直接处理,无系统依赖

### 运行时目录

服务首次写文件时自动创建以下目录,生产/容器部署需保证写权限:

- `backend/uploads/<project_id>/<bidder_id>/` — 投标人原压缩包
- `backend/extracted/<project_id>/<bidder_id>/<archive_hash>/` — 解压产物

两个目录都已加入 `.gitignore`。

### 部署 — 上传大小限制

`POST /api/projects/{pid}/bidders/` 与 `POST /api/projects/{pid}/bidders/{bid}/upload` 接受 ≤500MB multipart;反向代理需放开同等上限,否则 413 提前在反代层就会被拦下:

```nginx
client_max_body_size 500M;
```

uvicorn 自身没有 multipart 大小限制,但生产建议挂 nginx/Caddy 做边界防护。

## 常用命令

```bash
uvicorn app.main:app --reload                       # 启服务
alembic upgrade head                                # 迁移到最新
alembic downgrade -1                                # 回滚一档
pytest tests/unit/                                  # L1 单元
pytest tests/e2e/                                   # L2 接口 E2E
INFRA_DISABLE_LIFECYCLE=1 uvicorn ...               # 跳过生命周期清理(测试常用)
INFRA_DISABLE_EXTRACT=1 pytest ...                  # 跳过自动解压协程(L2 用 fixture 手动 await)
```
