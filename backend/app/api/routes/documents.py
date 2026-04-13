"""文档管理路由 - 投标文件上传与管理"""

from fastapi import APIRouter, UploadFile

router = APIRouter()


@router.post("/upload")
async def upload_document(file: UploadFile):
    """上传投标文件（支持 PDF/DOCX/XLSX）"""
    return {"filename": file.filename, "message": "TODO"}


@router.get("/{document_id}")
async def get_document(document_id: int):
    """获取文档详情"""
    return {"message": "TODO"}
