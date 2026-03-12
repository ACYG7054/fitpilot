"""描述 LangGraph 可变工作流状态的类型字典。"""

from typing import Any, Dict, List, Optional, TypedDict


class AgentState(TypedDict, total=False):
    """一次工作流执行过程中在各节点间流转的共享状态。"""

    session_id: str
    thread_id: str
    request_id: str
    client_ip: str
    question: str
    normalized_question: str
    intent: str
    route_reason: str
    pending_agents: List[str]
    approved_agents: List[str]
    active_agent: str
    react_rounds: Dict[str, int]
    review_rounds: Dict[str, int]
    retrieval_query: str
    reviewer_decision: str
    reviewer_feedback: str
    knowledge_hits: List[Dict[str, Any]]
    knowledge_answer: str
    location_answer: str
    user_location: Dict[str, Any]
    nearest_gym: Dict[str, Any]
    draft_answer: str
    final_answer: str
    requires_human: bool
    human_ticket_id: Optional[int]
    last_error: str
