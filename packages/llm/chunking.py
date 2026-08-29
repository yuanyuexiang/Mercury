"""文档解析与切分（技术方案 §6 RAG 细节）：md/txt/pdf/url → 带 metadata 的 chunk 列表。

markdown 的标题层级写入 metadata（h1/h2/h3）供检索过滤加权——即"轻量本体"（§6 定案）。
"""

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import structlog
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter

logger = structlog.get_logger()

# 目标约 400 token/块、overlap 60 token（§6）；中英混合按 ~2.5 字符/token 估算
CHUNK_SIZE_CHARS = 1000
CHUNK_OVERLAP_CHARS = 150


@dataclass
class ChunkData:
    chunk_index: int
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)


def checksum_of(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_source_text(
    source_type: str, storage_path: str | None = None, source_url: str | None = None
) -> str:
    if source_type in ("markdown", "txt"):
        if not storage_path:
            raise ValueError("markdown/txt 需要 storage_path")
        return Path(storage_path).read_text(encoding="utf-8")
    if source_type == "pdf":
        if not storage_path:
            raise ValueError("pdf 需要 storage_path")
        from pypdf import PdfReader

        reader = PdfReader(storage_path)
        return "\n\n".join((page.extract_text() or "") for page in reader.pages)
    if source_type == "url":
        if not source_url:
            raise ValueError("url 需要 source_url")
        import trafilatura

        # TODO(M8): SSRF 防护（§14）——M3 仅运营者脚本调用，不暴露给外部输入
        resp = httpx.get(source_url, timeout=20, follow_redirects=True)
        resp.raise_for_status()
        extracted = trafilatura.extract(resp.text)
        if not extracted:
            raise ValueError(f"无法从 {source_url} 提取正文")
        return extracted
    raise ValueError(f"未知 source_type: {source_type}")


def split_text(text: str, source_type: str) -> list[ChunkData]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE_CHARS, chunk_overlap=CHUNK_OVERLAP_CHARS
    )
    pieces: list[tuple[str, dict[str, Any]]] = []
    if source_type == "markdown":
        header_splitter = MarkdownHeaderTextSplitter(
            headers_to_split_on=[("#", "h1"), ("##", "h2"), ("###", "h3")]
        )
        for section in header_splitter.split_text(text):
            for piece in splitter.split_text(section.page_content):
                pieces.append((piece, dict(section.metadata)))
    else:
        pieces.extend((piece, {}) for piece in splitter.split_text(text))
    return [
        ChunkData(chunk_index=i, content=content, metadata=meta)
        for i, (content, meta) in enumerate(pieces)
        if content.strip()
    ]
