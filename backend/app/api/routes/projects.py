"""项目管理路由 - 每个检测任务对应一个项目"""

from fastapi import APIRouter

router = APIRouter()


@router.get("/")
async def list_projects():
    """获取所有检测项目列表"""
    return []


@router.post("/")
async def create_project():
    """创建新的检测项目"""
    return {"message": "TODO"}
