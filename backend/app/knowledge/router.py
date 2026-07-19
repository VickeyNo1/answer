import os
import shutil
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, status
from app.auth.deps import require_admin
from app.config import get_settings
from app.models import DocumentInfo
from app.knowledge.doc_parser import parse_file, chunk_text
from app.knowledge.embedding import embed_texts
from app.knowledge import chroma_service

router = APIRouter(prefix="/api/knowledge", tags=["知识库"])

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt"}


def _check_file(file: UploadFile) -> str:
    """校验文件格式和大小，返回文件扩展名"""
    settings = get_settings()
    filename = file.filename or "unknown"
    ext = os.path.splitext(filename)[1].lower()

    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="不支持的文件格式，仅支持 .pdf、.docx、.txt",
        )
    return ext


@router.post("/upload", status_code=status.HTTP_201_CREATED, response_model=DocumentInfo)
async def upload_document(
    file: UploadFile = File(...),
    subject_id: int | None = Form(None),
    current_user: dict = Depends(require_admin),
):
    """上传文档：解析 → 切分 → 向量化 → 入库（可指定所属科目）"""
    settings = get_settings()
    filename = file.filename or "unknown"

    # 1. 校验文件格式
    _check_file(file)

    # 2. 校验文件大小
    file_content = await file.read()
    max_size = settings.MAX_FILE_SIZE_MB * 1024 * 1024
    if len(file_content) > max_size:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"文件大小超过限制（最大 {settings.MAX_FILE_SIZE_MB}MB）",
        )

    # 3. 检查文档是否已存在
    if chroma_service.document_exists(filename):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="文档已存在，请先删除后重新上传",
        )

    # 4. 保存临时文件
    upload_dir = settings.UPLOAD_DIR
    os.makedirs(upload_dir, exist_ok=True)
    temp_path = os.path.join(upload_dir, filename)
    with open(temp_path, "wb") as f:
        f.write(file_content)

    try:
        # 5. 解析文档
        text = parse_file(temp_path)
        if not text.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="文档内容为空，无法上传",
            )

        # 6. 文本切分
        chunks = chunk_text(text, chunk_size=500, chunk_overlap=50)
        if not chunks:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="文档切分后无有效内容",
            )

        # 7. 向量化
        embeddings = embed_texts(chunks)

        # 8. 存入 ChromaDB
        chunk_count = chroma_service.add_document(filename, chunks, embeddings, subject_id or 0)

        return DocumentInfo(
            name=filename,
            chunk_count=chunk_count,
            created_at=datetime.now().isoformat(),
            subject_id=subject_id or 0,
        )

    finally:
        # 清理临时文件
        if os.path.exists(temp_path):
            os.remove(temp_path)


@router.get("/documents", response_model=list[DocumentInfo])
async def list_documents(
    current_user: dict = Depends(require_admin),
):
    """获取知识库文档列表"""
    docs = chroma_service.list_documents()
    return [
        DocumentInfo(
            name=doc["name"],
            chunk_count=doc["chunk_count"],
            created_at="",  # ChromaDB 不存储上传时间
            subject_id=doc.get("subject_id", 0),
        )
        for doc in docs
    ]


@router.delete("/documents/{name:path}")
async def delete_document(
    name: str,
    current_user: dict = Depends(require_admin),
):
    """删除文档及其向量数据"""
    if not chroma_service.delete_document(name):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="文档不存在",
        )
    return {"message": "ok"}
