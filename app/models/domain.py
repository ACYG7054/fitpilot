"""仓储层、服务层与图状态共享的领域模型。"""

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class KnowledgeChunk(BaseModel):
    """单个知识片段及其检索、重排相关分数。"""

    chunk_id: str
    content: str
    title: Optional[str] = None
    source: Optional[str] = None
    section: Optional[str] = None
    vector_score: float = 0.0
    keyword_score: float = 0.0
    rerank_score: float = 0.0
    metadata: Dict[str, Any] = Field(default_factory=dict)


class RoutingDecision(BaseModel):
    """路由节点输出的结构化决策结果。"""

    intent: Literal["knowledge", "gym", "hybrid", "unknown"]
    route_reason: str
    rewritten_query: str
    pending_agents: List[Literal["knowledge", "gym"]]


class ReactPlan(BaseModel):
    """知识代理在 ReAct 循环中的单步推理计划。"""

    thought: str
    need_retrieval: bool
    search_query: str
    answer_ready: bool


class ReviewDecision(BaseModel):
    """审核节点对当前草稿答案给出的结论。"""

    decision: Literal["approved", "revise", "escalate"]
    feedback: str
    confidence: float = 0.0


class UserLocationRecord(BaseModel):
    """由客户端 IP 解析出的用户位置。"""

    ip: str
    province: Optional[str] = None
    city: Optional[str] = None
    latitude: float
    longitude: float


class GymRecord(BaseModel):
    """仓储层与 MCP 工具统一返回的健身房数据。"""

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


class McpToolSpec(BaseModel):
    """通过轻量 MCP 接口暴露出去的工具定义。"""

    name: str
    description: str
    input_schema: Dict[str, Any]
