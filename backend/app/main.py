from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.routes import (
    admin,
    analysis,
    audit,
    auth,
    bidders,
    compare,
    documents,
    exports,
    parse_progress,
    price,
    price_items,
    projects,
    reports,
    reviews,
)
from app.api.routes.sse_demo import router as sse_demo_router
from app.core.config import settings
from app.db.session import engine
from app.services.lifecycle.cleanup import lifecycle_task


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: 启动生命周期 dry-run 任务(测试环境可通过 INFRA_DISABLE_LIFECYCLE=1 跳过)
    import logging
    import os
    import sys

    # config-llm-timeout-default:Windows 默认 GBK 控制台对含 U+00BA 等冷门字符的中文日志
    # 崩 UnicodeEncodeError,把 stdout/stderr 转成 utf-8 兜底(errors='replace' 防极端字符)。
    # 测试框架替换 stream / 容器化部署 stream 已非 TextIO wrapper 场景 → AttributeError/
    # ValueError,静默跳过不阻塞启动。
    for stream_name in ("stdout", "stderr"):
        try:
            getattr(sys, stream_name).reconfigure(
                encoding="utf-8", errors="replace"
            )
        except (AttributeError, ValueError):
            pass

    # test-infra-followup-wave2 Item 4:让 `app.*` logger 树级默认 INFO,方便 N3
    # 类诊断(input shape / output mix)在 uvicorn --log-level info 下自然可见。
    # 只设 logger level,不改 handler/formatter/dictConfig;prod handler 默认 warning
    # 级仍过滤 info 输出。try/except 兜 logging 初始化未就绪的极端场景。
    try:
        logging.getLogger("app").setLevel(logging.INFO)
    except Exception:  # noqa: BLE001 - logging 失败不阻塞启动
        pass

    startup_logger = logging.getLogger("app.startup")

    task = None
    if os.environ.get("INFRA_DISABLE_LIFECYCLE") != "1":
        task = lifecycle_task.start()

    # C15: 导出文件 7 天过期清理(每日 02:00)
    export_cleanup_handle = None
    if os.environ.get("INFRA_DISABLE_EXPORT_CLEANUP") != "1":
        from app.services.export.cleanup import export_cleanup_task

        export_cleanup_handle = export_cleanup_task.start()

    # DEF-003: seed admin(首次启动自动创建管理员)
    # INFRA_DISABLE_SEED=1 可跳过(L2 测试用)
    if os.environ.get("INFRA_DISABLE_SEED") != "1":
        try:
            from app.services.auth.seed import ensure_seed_admin

            await ensure_seed_admin()
        except Exception as exc:  # noqa: BLE001 - seed 异常不能阻塞启动
            startup_logger.exception("admin seed failure: %s", exc)

    # C6: 启动时扫描 stuck async_tasks 并回滚实体状态
    # INFRA_DISABLE_SCANNER=1 可跳过(L2 测试用)
    if os.environ.get("INFRA_DISABLE_SCANNER") != "1":
        try:
            from app.services.async_tasks.scanner import scan_and_recover

            await scan_and_recover()
        except Exception as exc:  # noqa: BLE001 - scanner 异常不能阻塞启动
            startup_logger.exception("scanner startup failure: %s", exc)

    # admin-llm-config bootstrap:把 DB 里的 LLM 配置推到 runtime settings,
    # 让同步版 get_llm_provider()(pipeline/Agent 用)也读到最新值。
    # 失败不阻塞启动(DB 无 llm 段时 read_llm_config 会走 env 回退,无副作用)
    try:
        from app.core.config import settings as _settings
        from app.db.session import async_session
        from app.services.admin.llm_reader import read_llm_config

        async with async_session() as s:
            cfg = await read_llm_config(s)
            if cfg.source == "db":
                _settings.llm_provider = cfg.provider
                _settings.llm_api_key = cfg.api_key
                _settings.llm_model = cfg.model
                _settings.llm_base_url = cfg.base_url
                _settings.llm_timeout_s = float(cfg.timeout_s)
                startup_logger.info(
                    "admin-llm-config bootstrap: settings overridden from DB (provider=%s)",
                    cfg.provider,
                )
    except Exception as exc:  # noqa: BLE001
        startup_logger.exception("admin-llm-config bootstrap failure: %s", exc)

    yield

    # Shutdown
    if task is not None:
        await lifecycle_task.stop(task)

    if export_cleanup_handle is not None:
        from app.services.export.cleanup import export_cleanup_task

        await export_cleanup_task.stop(export_cleanup_handle)

    # C6: 释放 ProcessPoolExecutor(若 C7+ 真 Agent 消费了)
    try:
        from app.services.detect.engine import shutdown_cpu_executor

        shutdown_cpu_executor()
    except Exception:  # noqa: BLE001
        pass


app = FastAPI(
    title="围标检测系统",
    description="投标文件分析与围标串标行为检测 API",
    version="0.1.0",
    lifespan=lifespan,
    redirect_slashes=False,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(admin.router, prefix="/api/admin", tags=["admin"])
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(projects.router, prefix="/api/projects", tags=["projects"])
# C4 投标人路由挂在 /api/projects/{project_id}/bidders 下;path param 由路由
# 函数签名声明,prefix 直接拼字面量
app.include_router(
    bidders.router,
    prefix="/api/projects/{project_id}/bidders",
    tags=["bidders"],
)
app.include_router(documents.router, prefix="/api/documents", tags=["documents"])
# C4 报价配置/规则 路由共用 /api/projects 前缀,与 projects 路由错开 path
app.include_router(price.router, prefix="/api/projects", tags=["price"])
# C5 报价项查询
app.include_router(price_items.router, prefix="/api/projects", tags=["price-items"])
# C5 解析进度 SSE
app.include_router(
    parse_progress.router, prefix="/api/projects", tags=["parse-progress"]
)
# C6 检测路由:/api/projects/{pid}/analysis/{start,status,events}
app.include_router(analysis.router, prefix="/api/projects", tags=["analysis"])
# C6 报告路由:/api/projects/{pid}/reports/{version}
app.include_router(reports.router, prefix="/api/projects", tags=["reports"])
# C15 审计日志查询:/api/projects/{pid}/audit_logs
app.include_router(audit.router, prefix="/api/projects", tags=["audit"])
# C15 人工复核:/api/projects/{pid}/reports/{version}/(review|dimensions/{dim}/review)
app.include_router(reviews.router, prefix="/api/projects", tags=["reviews"])
# C15 Word 导出触发:/api/projects/{pid}/reports/{version}/export
app.include_router(exports.projects_router, prefix="/api/projects", tags=["exports"])
# C15 Word 导出下载:/api/exports/{job_id}/download
app.include_router(exports.exports_router, prefix="/api/exports", tags=["exports"])
# C16 对比视图:/api/projects/{pid}/compare/{text,price,metadata}
app.include_router(compare.router, prefix="/api/projects", tags=["compare"])
app.include_router(sse_demo_router, prefix="/demo", tags=["demo"])


@app.get("/api/health")
async def health_check():
    """健康检查:服务存活 + DB 连通性。DB 不可达返回 503。"""
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return {"status": "ok", "db": "ok"}
    except Exception as exc:  # noqa: BLE001 - 健康检查故意捕获所有,返回 503
        return JSONResponse(
            status_code=503,
            content={
                "status": "degraded",
                "db": "unreachable",
                "detail": str(exc)[:200],
            },
        )
