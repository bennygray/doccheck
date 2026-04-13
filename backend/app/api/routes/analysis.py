"""分析路由 - 围标检测分析"""

from fastapi import APIRouter

router = APIRouter()


@router.post("/start/{project_id}")
async def start_analysis(project_id: int):
    """启动围标检测分析"""
    return {"message": "TODO"}


@router.get("/result/{project_id}")
async def get_analysis_result(project_id: int):
    """获取分析结果"""
    return {"message": "TODO"}
