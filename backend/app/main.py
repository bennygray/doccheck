from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.routes import (
    analysis,
    auth,
    bidders,
    documents,
    parse_progress,
    price,
    price_items,
    projects,
    reports,
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

    startup_logger = logging.getLogger("app.startup")

    task = None
    if os.environ.get("INFRA_DISABLE_LIFECYCLE") != "1":
        task = lifecycle_task.start()

    # C6: 启动时扫描 stuck async_tasks 并回滚实体状态
    # INFRA_DISABLE_SCANNER=1 可跳过(L2 测试用)
    if os.environ.get("INFRA_DISABLE_SCANNER") != "1":
        try:
            from app.services.async_tasks.scanner import scan_and_recover

            await scan_and_recover()
        except Exception as exc:  # noqa: BLE001 - scanner 异常不能阻塞启动
            startup_logger.exception("scanner startup failure: %s", exc)

    yield

    # Shutdown
    if task is not None:
        await lifecycle_task.stop(task)

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
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
