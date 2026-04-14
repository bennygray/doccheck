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

### C5 parser-pipeline 依赖

C5 引入文档内容提取 + LLM 解析:

- **python-docx / openpyxl / Pillow / imagehash / lxml**:已在 `pyproject.toml`,`uv sync` 自动装
  - Pillow 在 Linux 可能需要 `apt-get install libjpeg-dev` 才能解 JPG 图片
- **LLM Provider**:通过环境变量配置(`app/services/llm/factory.py`):
  - `LLM_PROVIDER=openai` (默认) / `dashscope` / 其他 OpenAI-compat
  - `LLM_API_KEY=<key>`(必填,生产部署)
  - `LLM_BASE_URL=<url>`(可选,覆盖默认 base url)
  - `LLM_MODEL=<model name>`(默认 gpt-4o-mini,按 provider 调整)
  - `LLM_TIMEOUT_S=30`(默认 30s)
- **SSE 反代配置**(`/api/projects/{pid}/parse-progress`):
  ```nginx
  proxy_read_timeout 60s;       # >= heartbeat 间隔(15s)+ 余量
  proxy_buffering off;          # 与响应头 X-Accel-Buffering: no 配合
  ```

### C5 运行时环境变量

- `INFRA_DISABLE_PIPELINE=1`:禁用 pipeline 自动触发(L2 测试用,手动 await run_pipeline)
- `SSE_HEARTBEAT_INTERVAL_S=15`:SSE 心跳间隔(测试可缩短到 0.2)

### 部署 — 上传大小限制

`POST /api/projects/{pid}/bidders/` 与 `POST /api/projects/{pid}/bidders/{bid}/upload` 接受 ≤500MB multipart;反向代理需放开同等上限,否则 413 提前在反代层就会被拦下:

```nginx
client_max_body_size 500M;
```

uvicorn 自身没有 multipart 大小限制,但生产建议挂 nginx/Caddy 做边界防护。

### C6 detect-framework 依赖

C6 引入异步检测框架 + 10 Agent 骨架 + SSE 检测推送 + 通用任务表:

- **无新系统 / 第三方依赖**:纯 asyncio + SQLAlchemy + 复用 C5 progress_broker
- **启动时扫描 stuck 任务**:FastAPI lifespan startup 调 `scanner.scan_and_recover()`,心跳过期的 `async_tasks` 行会触发回滚 handler(extract / content_parse / llm_classify / agent_run 4 subtype)
- **ProcessPoolExecutor 接口预留**:`app/services/detect/engine.get_cpu_executor()`,C6 dummy Agent 不消费,C7+ 真 CPU Agent 调用
- **SSE 端点**:`/api/projects/{pid}/analysis/events`;nginx 同 C5 `proxy_read_timeout ≥ 60s` + `proxy_buffering off`

环境变量:

- `AGENT_TIMEOUT_S`(默认 300)— 单 Agent 超时秒数
- `GLOBAL_TIMEOUT_S`(默认 1800)— 整轮检测全局超时秒数
- `ASYNC_TASK_HEARTBEAT_S`(默认 30)— 心跳更新间隔
- `ASYNC_TASK_STUCK_THRESHOLD_S`(默认 60)— scanner 判 stuck 阈值
- `ASYNC_TASK_MAX_SCAN_ROWS`(默认 1000)— scanner 单次处理上限
- `INFRA_DISABLE_DETECT=1` — 测试用:`POST /analysis/start` 仅创建 AgentTask 行,不 asyncio.create_task 调度
- `INFRA_DISABLE_SCANNER=1` — 测试用:跳过 lifespan startup 的 scanner 扫描

### C7 detect-agent-text-similarity 依赖

C7 把 `text_similarity` Agent 的 `run()` 从 dummy 替换为真实双轨算法(本地 TF-IDF + LLM 定性),C8~C13 陆续替换其余 9 个 Agent。

- **零新增第三方依赖**:jieba / scikit-learn / numpy 均 C5 已引入
- **ProcessPoolExecutor 首个真消费者**:CPU 密集段(TF-IDF + cosine)走 `get_cpu_executor() + loop.run_in_executor()`;首个 pair 有 ~1s jieba + sklearn 子进程冷启动开销,后续复用 worker 无感知
- **LLM 调用**:按 requirements §10.8 L-4 prompt,LLM 失败(timeout / bad_json × 2)→ 降级为仅程序相似度,`evidence_json.degraded=true`,`AgentTask.status=succeeded`(降级非失败)
- **容器 cpu_count 验证**(C6 Q3 延伸):部署到容器后跑 `docker exec backend python -c "import os; print(os.cpu_count())"`,若显著高于实际限额开独立 follow-up

环境变量(均可运行期调,文档级 C7 默认对小规模项目):

- `TEXT_SIM_MIN_DOC_CHARS`(默认 500)— 单侧选中文档总字符 < 此值 preflight 返 `skip "文档过短无法对比"`
- `TEXT_SIM_PAIR_SCORE_THRESHOLD`(默认 0.70)— 段落对 cosine 相似度 ≥ 此值才进 LLM 候选
- `TEXT_SIM_MAX_PAIRS_TO_LLM`(默认 30)— 单 pair 最多发 LLM 的段落对数(防 token 爆炸)

## 常用命令

```bash
uvicorn app.main:app --reload                       # 启服务
alembic upgrade head                                # 迁移到最新
alembic downgrade -1                                # 回滚一档
pytest tests/unit/                                  # L1 单元
pytest tests/e2e/                                   # L2 接口 E2E
INFRA_DISABLE_LIFECYCLE=1 uvicorn ...               # 跳过生命周期清理(测试常用)
INFRA_DISABLE_EXTRACT=1 pytest ...                  # 跳过自动解压协程(L2 用 fixture 手动 await)
INFRA_DISABLE_PIPELINE=1 pytest ...                 # 跳过解析流水线协程(C5 L2 用 fixture 手动 await)
INFRA_DISABLE_DETECT=1 pytest ...                   # 跳过自动检测调度(C6 L2 用 fixture 手动 await)
```
