"""知识库后台 API（技术方案 §10）：上传/URL 导入、启停、重建索引、删除。"""

import hashlib
import time
from pathlib import Path
from typing import Any

import structlog
from domain import repositories
from domain.models import KnowledgeChunk, KnowledgeDocument
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from observability.logging import new_trace_id
from pydantic import BaseModel
from sqlalchemy import delete, select

from api.deps import AdminRead, AdminWrite
from api.netguard import assert_public_http_url

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])
logger = structlog.get_logger()

MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # §14：≤20MB
SUFFIX_TO_TYPE = {".md": "markdown", ".markdown": "markdown", ".txt": "txt", ".pdf": "pdf"}


def _doc_out(doc: KnowledgeDocument) -> dict[str, Any]:
    return {
        "id": doc.id,
        "title": doc.title,
        "source_type": doc.source_type,
        "source_url": doc.source_url,
        "status": doc.status,
        "version": doc.version,
        "updated_at": doc.updated_at.isoformat(),
    }


@router.get("/documents", dependencies=AdminRead)
async def list_documents(request: Request) -> dict[str, Any]:
    async with request.app.state.session_factory() as session:
        docs = (
            (await session.execute(select(KnowledgeDocument).order_by(KnowledgeDocument.id)))
            .scalars()
            .all()
        )
    return {"items": [_doc_out(d) for d in docs]}


async def _enqueue_index(request: Request, document_id: int) -> None:
    await request.app.state.arq.enqueue_job("index_document", document_id, new_trace_id())


@router.post("/documents", dependencies=AdminWrite)
async def upload_document(
    request: Request,
    file: UploadFile | None = File(default=None),  # noqa: B008  (FastAPI 惯用法)
    title: str | None = Form(default=None),
) -> dict[str, Any]:
    """multipart 文件上传（md/txt/pdf）。URL 导入走 POST /documents/url。"""
    if file is None or not file.filename:
        raise HTTPException(status_code=422, detail="缺少文件")
    suffix = Path(file.filename).suffix.lower()
    source_type = SUFFIX_TO_TYPE.get(suffix)
    if source_type is None:
        raise HTTPException(
            status_code=422,
            detail=(
                f"暂不支持 {suffix} 文件：请用 Markdown / TXT / PDF（Word 文档可另存为 PDF 后上传）"
            ),
        )
    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="文件超过 20MB 上限")

    settings = request.app.state.settings
    storage = Path(settings.storage_dir)
    storage.mkdir(parents=True, exist_ok=True)  # noqa: ASYNC240
    checksum = hashlib.sha256(content).hexdigest()
    path = storage / f"{int(time.time())}_{checksum[:8]}{suffix}"
    path.write_bytes(content)  # noqa: ASYNC240  (小文件一次性写，接受阻塞)

    async with request.app.state.session_factory() as session:
        existing = await repositories.find_document_by_checksum(session, checksum)
        if existing is not None:
            raise HTTPException(status_code=409, detail=f"相同内容的文档已存在（id={existing.id}）")
        doc = await repositories.create_document(
            session,
            title=title or Path(file.filename).stem,
            source_type=source_type,
            storage_path=str(path),
            checksum=checksum,
        )
        await session.commit()
        document_id = doc.id
    await _enqueue_index(request, document_id)
    return {"id": document_id, "status": "pending"}


class UrlImport(BaseModel):
    url: str
    title: str


@router.post("/documents/url", dependencies=AdminWrite)
async def import_url(request: Request, body: UrlImport) -> dict[str, Any]:
    assert_public_http_url(body.url)  # §14 SSRF 防护
    async with request.app.state.session_factory() as session:
        doc = await repositories.create_document(
            session, title=body.title, source_type="url", source_url=body.url
        )
        await session.commit()
        document_id = doc.id
    await _enqueue_index(request, document_id)
    return {"id": document_id, "status": "pending"}


class DocumentPatch(BaseModel):
    status: str  # active|disabled


@router.patch("/documents/{document_id}", dependencies=AdminWrite)
async def patch_document(request: Request, document_id: int, body: DocumentPatch) -> dict[str, Any]:
    if body.status not in ("active", "disabled"):
        raise HTTPException(status_code=422, detail="status 仅支持 active/disabled")
    async with request.app.state.session_factory() as session:
        doc = await repositories.get_document(session, document_id)
        if doc is None:
            raise HTTPException(status_code=404)
        await repositories.set_document_status(session, document_id, body.status)
        await session.commit()
        await session.refresh(doc)
        return _doc_out(doc)


@router.post("/documents/{document_id}/reindex", dependencies=AdminWrite)
async def reindex_document(request: Request, document_id: int) -> dict[str, str]:
    async with request.app.state.session_factory() as session:
        if await repositories.get_document(session, document_id) is None:
            raise HTTPException(status_code=404)
    await _enqueue_index(request, document_id)
    return {"status": "queued"}


@router.delete("/documents/{document_id}", dependencies=AdminWrite)
async def delete_document(request: Request, document_id: int) -> dict[str, bool]:
    async with request.app.state.session_factory() as session:
        doc = await repositories.get_document(session, document_id)
        if doc is None:
            raise HTTPException(status_code=404)
        await session.execute(
            delete(KnowledgeChunk).where(KnowledgeChunk.document_id == document_id)
        )
        storage_path = doc.storage_path
        await session.delete(doc)
        await session.commit()
    if storage_path:
        Path(storage_path).unlink(missing_ok=True)  # noqa: ASYNC240  # 原始文件一并清理（§14）
    return {"ok": True}
