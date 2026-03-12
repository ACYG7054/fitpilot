"""HTTP API 对外暴露的请求与响应模型。"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class SourceChunk(BaseModel):
    """返回给调用方的精简知识片段。"""

    chunk_id: str
    title: Optional[str] = None
    source: Optional[str] = None
    score: float = 0.0
    snippet: str


class GymRecommendation(BaseModel):
    """聊天响应中返回的健身房推荐信息。"""

    gym_id: int
    name: str
    address: str
    city: str
    latitude: float
    longitude: float
    distance_km: float
    business_hours: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    navigation_url: Optional[str] = None


class ChatRequest(BaseModel):
    """同步与流式聊天接口共用的请求体。"""

    session_id: Optional[str] = None
    thread_id: Optional[str] = None
    question: str = Field(min_length=1, max_length=4000)
    client_ip: Optional[str] = None


class ChatResponse(BaseModel):
    """由图状态整理出的统一聊天响应。"""

    session_id: str
    thread_id: str
    request_id: str
    intent: str
    answer: Optional[str] = None
    requires_human: bool = False
    human_ticket_id: Optional[int] = None
    reviewer_decision: Optional[str] = None
    reviewer_feedback: Optional[str] = None
    knowledge_sources: List[SourceChunk] = Field(default_factory=list)
    nearest_gym: Optional[GymRecommendation] = None


class HumanResumeRequest(BaseModel):
    """用于人工介入后恢复工作流的请求体。"""

    approved: bool = True
    final_answer: Optional[str] = None
    note: Optional[str] = None


class KnowledgeDocumentIn(BaseModel):
    """待写入 Chroma 知识库的单条文档。"""

    document_id: str = Field(min_length=1, max_length=128)
    content: str = Field(min_length=1)
    title: Optional[str] = None
    source: Optional[str] = None
    section: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class KnowledgeIngestRequest(BaseModel):
    """批量知识入库请求。"""

    documents: List[KnowledgeDocumentIn] = Field(min_length=1)


class KnowledgeSearchRequest(BaseModel):
    """直接查询知识库时使用的请求体。"""

    query: str = Field(min_length=1)
    top_k: int = Field(default=5, ge=1, le=10)


class KnowledgeSearchResponse(BaseModel):
    """知识检索接口返回的结果集合。"""

    query: str
    hits: List[SourceChunk]
