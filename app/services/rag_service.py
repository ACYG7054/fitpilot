"""对 Chroma 服务做轻量封装的 RAG 服务层。"""

from typing import List

from app.core.config import Settings
from app.models.api import KnowledgeDocumentIn
from app.models.domain import KnowledgeChunk
from app.services.chroma_service import ChromaService


class RagService:
    """为图流程提供入库、检索和上下文拼装能力。"""

    def __init__(self, chroma_service: ChromaService, settings: Settings) -> None:
        self.chroma_service = chroma_service
        self.settings = settings

    async def ingest_documents(self, documents: List[KnowledgeDocumentIn]) -> int:
        """向向量库插入或更新知识文档。"""
        return await self.chroma_service.upsert_documents(documents)

    async def retrieve(self, query: str, top_k: int = 0) -> List[KnowledgeChunk]:
        """执行混合检索；未指定时使用配置中的默认 `top_k`。"""
        return await self.chroma_service.hybrid_search(query, top_k=top_k or self.settings.rag_top_k)

    def build_context(self, chunks: List[KnowledgeChunk]) -> str:
        """把检索到的片段整理成紧凑的提示词上下文。"""
        context_parts: List[str] = []
        for index, chunk in enumerate(chunks, start=1):
            title = chunk.title or chunk.source or f"Chunk {index}"
            snippet = chunk.content[: self.settings.rag_max_context_chars]
            context_parts.append(f"[{index}] {title}\n{snippet}")
        return "\n\n".join(context_parts)
