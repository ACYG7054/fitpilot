"""知识库入库与检索接口。"""

from fastapi import APIRouter, Depends

from app.api.dependencies import get_container
from app.models.api import KnowledgeIngestRequest, KnowledgeSearchRequest, KnowledgeSearchResponse, SourceChunk
from app.runtime.container import AppContainer


router = APIRouter()


@router.post("/documents")
async def ingest_documents(
    request_model: KnowledgeIngestRequest,
    container: AppContainer = Depends(get_container),
) -> dict:
    """把知识文档写入 Chroma 集合。"""
    count = await container.rag_service.ingest_documents(request_model.documents)
    return {"ingested": count}


@router.post("/search", response_model=KnowledgeSearchResponse)
async def search_knowledge(
    request_model: KnowledgeSearchRequest,
    container: AppContainer = Depends(get_container),
) -> KnowledgeSearchResponse:
    """绕过图流程，直接检索知识库。"""
    hits = await container.rag_service.retrieve(request_model.query, top_k=request_model.top_k)
    return KnowledgeSearchResponse(
        query=request_model.query,
        hits=[
            SourceChunk(
                chunk_id=item.chunk_id,
                title=item.title,
                source=item.source,
                score=item.rerank_score,
                snippet=item.content[:220],
            )
            for item in hits
        ],
    )
