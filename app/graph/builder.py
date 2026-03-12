"""FitPilot 的 LangGraph 工作流组装与节点实现。"""

import json
from typing import Any, Dict, List

import httpx
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, RetryPolicy, interrupt
from openai import APIConnectionError, APITimeoutError, InternalServerError, RateLimitError

from app.core.config import Settings
from app.core.errors import HumanInterventionRequiredError, JsonOutputParseError
from app.core.events import emit_graph_event
from app.graph.prompts import (
    GYM_ANSWER_SYSTEM_PROMPT,
    KNOWLEDGE_ANSWER_SYSTEM_PROMPT,
    KNOWLEDGE_REASONER_SYSTEM_PROMPT,
    REVIEWER_SYSTEM_PROMPT,
    ROUTER_SYSTEM_PROMPT,
)
from app.graph.state import AgentState
from app.models.domain import GymRecord, KnowledgeChunk, ReactPlan, ReviewDecision, RoutingDecision, UserLocationRecord
from app.repositories.human_ticket_repository import HumanTicketRepository
from app.services.openai_service import OpenAIService
from app.services.rag_service import RagService
from app.mcp.protocol import McpClient


RETRYABLE_GRAPH_EXCEPTIONS = (
    APIConnectionError,
    APITimeoutError,
    InternalServerError,
    RateLimitError,
    httpx.HTTPError,
    JsonOutputParseError,
)


def graph_retry_predicate(exc: Exception) -> bool:
    """判断图节点失败后是否应该由 LangGraph 自动重试。"""
    return isinstance(exc, RETRYABLE_GRAPH_EXCEPTIONS)


class FitPilotGraphFactory:
    """负责构建并实现路由-专家-审核的工作流图。"""

    def __init__(
        self,
        *,
        settings: Settings,
        openai_service: OpenAIService,
        rag_service: RagService,
        mcp_client: McpClient,
        human_ticket_repository: HumanTicketRepository,
    ) -> None:
        self.settings = settings
        self.openai_service = openai_service
        self.rag_service = rag_service
        self.mcp_client = mcp_client
        self.human_ticket_repository = human_ticket_repository

    def build(self) -> Any:
        """组装节点、连接边，并编译 LangGraph 状态机。"""
        # 图流程采用 router -> specialist -> reviewer 的循环，超过限制后再升级到人工处理。
        graph = StateGraph(AgentState)

        graph.add_node("router", self.router_node, retry_policy=self._node_retry_policy())
        graph.add_node("dispatch_agent", self.dispatch_agent_node)
        graph.add_node("knowledge_reasoner", self.knowledge_reasoner_node, retry_policy=self._node_retry_policy())
        graph.add_node("knowledge_retrieve", self.knowledge_retrieve_node, retry_policy=self._node_retry_policy())
        graph.add_node("knowledge_answer", self.knowledge_answer_node, retry_policy=self._node_retry_policy())
        graph.add_node("gym_agent", self.gym_agent_node, retry_policy=self._node_retry_policy())
        graph.add_node("reviewer", self.reviewer_node, retry_policy=self._node_retry_policy())
        graph.add_node("finalize", self.finalize_node)
        graph.add_node("human_escalation", self.human_escalation_node)

        graph.add_edge(START, "router")
        graph.add_edge("finalize", END)
        graph.add_edge("human_escalation", END)

        return graph.compile(checkpointer=InMemorySaver())

    def _node_retry_policy(self) -> RetryPolicy:
        """返回适用于 LLM 与工具节点的统一重试策略。"""
        return RetryPolicy(max_attempts=2, retry_on=graph_retry_predicate)

    async def router_node(self, state: AgentState) -> Command:
        """识别用户意图，并初始化与路由相关的状态字段。"""
        question = state["question"].strip()
        normalized_question = question
        await emit_graph_event("thinking", "router", {"question": question})

        try:
            routing = await self.openai_service.chat_json(
                model=self.settings.router_model,
                system_prompt=ROUTER_SYSTEM_PROMPT,
                user_prompt=f"User question:\n{question}",
                output_model=RoutingDecision,
            )
        except HumanInterventionRequiredError:
            routing = self._heuristic_route(question)

        next_update: Dict[str, Any] = {
            "normalized_question": routing.rewritten_query or normalized_question,
            "intent": routing.intent,
            "route_reason": routing.route_reason,
            "pending_agents": routing.pending_agents,
            "approved_agents": [],
            "react_rounds": {},
            "review_rounds": {},
            "reviewer_feedback": "",
            "reviewer_decision": "",
        }
        await emit_graph_event(
            "handoff",
            "router",
            {"intent": routing.intent, "pending_agents": routing.pending_agents, "reason": routing.route_reason},
        )
        return Command(goto="dispatch_agent", update=next_update)

    async def dispatch_agent_node(self, state: AgentState) -> Command:
        """挑选下一个尚未完成的专家代理节点。"""
        approved_agents = set(state.get("approved_agents", []))
        pending_agents = state.get("pending_agents", [])
        remaining_agents = [agent for agent in pending_agents if agent not in approved_agents]
        if not remaining_agents:
            return Command(goto="finalize")

        next_agent = remaining_agents[0]
        await emit_graph_event("handoff", "dispatch_agent", {"next_agent": next_agent})
        if next_agent == "knowledge":
            return Command(goto="knowledge_reasoner", update={"active_agent": "knowledge"})
        return Command(goto="gym_agent", update={"active_agent": "gym"})

    async def knowledge_reasoner_node(self, state: AgentState) -> Command:
        """执行知识代理的 ReAct 规划步骤，并决定是否继续检索。"""
        react_rounds = dict(state.get("react_rounds", {}))
        current_round = react_rounds.get("knowledge", 0) + 1
        react_rounds["knowledge"] = current_round

        if current_round > self.settings.react_max_rounds:
            return self._to_human_command(
                state,
                reason="知识检索轮次已超过上限，建议人工复核。",
                update={"react_rounds": react_rounds},
            )

        retrieval_count = len(state.get("knowledge_hits", []))
        reviewer_feedback = state.get("reviewer_feedback", "")
        plan = await self.openai_service.chat_json(
            model=self.settings.chat_model,
            system_prompt=KNOWLEDGE_REASONER_SYSTEM_PROMPT,
            user_prompt=(
                f"User question:\n{state['question']}\n\n"
                f"Current rewritten query:\n{state.get('normalized_question', state['question'])}\n\n"
                f"Current retrieval count: {retrieval_count}\n"
                f"Reviewer feedback: {reviewer_feedback or 'none'}"
            ),
            output_model=ReactPlan,
        )
        await emit_graph_event(
            "thinking",
            "knowledge_reasoner",
            {
                "round": current_round,
                "thought": plan.thought,
                "need_retrieval": plan.need_retrieval,
                "search_query": plan.search_query,
            },
        )

        retrieval_query = plan.search_query or state.get("normalized_question") or state["question"]
        # ReAct 循环要么继续补证据，要么直接进入答案生成阶段。
        if plan.need_retrieval or not state.get("knowledge_hits"):
            return Command(
                goto="knowledge_retrieve",
                update={"react_rounds": react_rounds, "retrieval_query": retrieval_query},
            )
        return Command(
            goto="knowledge_answer",
            update={"react_rounds": react_rounds, "retrieval_query": retrieval_query},
        )

    async def knowledge_retrieve_node(self, state: AgentState) -> Command:
        """从混合检索结果中召回候选知识片段。"""
        retrieval_query = state.get("retrieval_query") or state.get("normalized_question") or state["question"]
        await emit_graph_event(
            "tool_start",
            "knowledge_retrieve",
            {"tool_name": "chroma_hybrid_search", "query": retrieval_query},
        )
        chunks = await self.rag_service.retrieve(retrieval_query, top_k=self.settings.rag_top_k)
        await emit_graph_event(
            "tool_end",
            "knowledge_retrieve",
            {"tool_name": "chroma_hybrid_search", "hit_count": len(chunks)},
        )

        if not chunks:
            # 私有知识库没有命中时，再给代理一次改写检索词的机会。
            current_round = dict(state.get("react_rounds", {})).get("knowledge", 1)
            if current_round >= self.settings.react_max_rounds:
                return self._to_human_command(
                    state,
                    reason="知识库未命中有效内容，自动改写查询后仍无结果。",
                    update={"last_error": "Knowledge base returned zero hits."},
                )
            return Command(
                goto="knowledge_reasoner",
                update={
                    "reviewer_feedback": "知识库未命中，请缩小问题范围并重写检索词。",
                    "knowledge_hits": [],
                },
            )

        return Command(
            goto="knowledge_answer",
            update={"knowledge_hits": [chunk.model_dump() for chunk in chunks]},
        )

    async def knowledge_answer_node(self, state: AgentState) -> Dict[str, Any]:
        """基于检索上下文生成有证据支撑的知识答案。"""
        chunks = [KnowledgeChunk.model_validate(item) for item in state.get("knowledge_hits", [])]
        context_text = self.rag_service.build_context(chunks)
        reviewer_feedback = state.get("reviewer_feedback", "")

        async def on_token(token: str) -> None:
            await emit_graph_event("token", "knowledge_answer", {"text": token, "agent": "knowledge"})

        answer = await self.openai_service.stream_text(
            model=self.settings.chat_model,
            system_prompt=KNOWLEDGE_ANSWER_SYSTEM_PROMPT,
            user_prompt=(
                f"User question:\n{state['question']}\n\n"
                f"Reviewer feedback:\n{reviewer_feedback or 'none'}\n\n"
                f"Retrieved evidence:\n{context_text}"
            ),
            on_token=on_token,
        )
        return {
            "active_agent": "knowledge",
            "knowledge_answer": answer.strip(),
            "draft_answer": answer.strip(),
            "reviewer_feedback": "",
        }

    async def gym_agent_node(self, state: AgentState) -> Dict[str, Any]:
        """通过 MCP 工具查询最近健身房，并组织最终回答。"""
        client_ip = state.get("client_ip", "").strip()
        if not client_ip:
            raise HumanInterventionRequiredError(
                "Client IP is required for local gym lookup.",
                stage="gym_lookup",
                details={"request_id": state.get("request_id")},
            )

        await emit_graph_event("tool_start", "gym_agent", {"tool_name": "find_nearest_gym", "client_ip": client_ip})
        # 位置代理只通过 MCP 客户端访问工具，这样未来新增插件时不必改代理契约。
        nearest_gym_package = await self.mcp_client.call_tool("find_nearest_gym", {"client_ip": client_ip})
        await emit_graph_event(
            "tool_end",
            "gym_agent",
            {"tool_name": "find_nearest_gym", "payload_keys": list(nearest_gym_package.keys())},
        )

        user_location = UserLocationRecord.model_validate(nearest_gym_package["user_location"])
        nearest_gym = GymRecord.model_validate(nearest_gym_package["nearest_gym"])

        # 导航链接单独作为第二次工具调用生成，便于后续替换地图提供方。
        await emit_graph_event("tool_start", "gym_agent", {"tool_name": "build_baidu_navigation_url"})
        nav_payload = await self.mcp_client.call_tool(
            "build_baidu_navigation_url",
            {
                "user_location": user_location.model_dump(),
                "nearest_gym": nearest_gym.model_dump(),
            },
        )
        nearest_gym.navigation_url = nav_payload["navigation_url"]
        await emit_graph_event("tool_end", "gym_agent", {"tool_name": "build_baidu_navigation_url"})

        reviewer_feedback = state.get("reviewer_feedback", "")
        try:
            async def on_token(token: str) -> None:
                await emit_graph_event("token", "gym_agent", {"text": token, "agent": "gym"})

            answer = await self.openai_service.stream_text(
                model=self.settings.chat_model,
                system_prompt=GYM_ANSWER_SYSTEM_PROMPT,
                user_prompt=(
                    f"User question:\n{state['question']}\n\n"
                    f"Reviewer feedback:\n{reviewer_feedback or 'none'}\n\n"
                    f"Structured tool output:\n"
                    f"{json.dumps({'user_location': user_location.model_dump(), 'nearest_gym': nearest_gym.model_dump()}, ensure_ascii=False)}"
                ),
                on_token=on_token,
            )
        except HumanInterventionRequiredError:
            answer = self._fallback_gym_answer(user_location, nearest_gym)

        return {
            "active_agent": "gym",
            "user_location": user_location.model_dump(),
            "nearest_gym": nearest_gym.model_dump(),
            "location_answer": answer.strip(),
            "draft_answer": answer.strip(),
            "reviewer_feedback": "",
        }

    async def reviewer_node(self, state: AgentState) -> Command:
        """审核最新专家草稿，并决定通过、返修或升级人工。"""
        active_agent = state.get("active_agent", "")
        review_rounds = dict(state.get("review_rounds", {}))
        current_round = review_rounds.get(active_agent, 0) + 1
        review_rounds[active_agent] = current_round

        if current_round > self.settings.reviewer_max_rounds:
            return self._to_human_command(
                state,
                reason="Reviewer质检轮次已超过上限，建议人工介入。",
                update={"review_rounds": review_rounds},
            )

        evidence = self._review_evidence(state)
        try:
            decision = await self.openai_service.chat_json(
                model=self.settings.reviewer_model,
                system_prompt=REVIEWER_SYSTEM_PROMPT,
                user_prompt=(
                    f"Active agent: {active_agent}\n\n"
                    f"User question:\n{state['question']}\n\n"
                    f"Draft answer:\n{state.get('draft_answer', '')}\n\n"
                    f"Evidence:\n{evidence}\n\n"
                    f"Previous reviewer feedback:\n{state.get('reviewer_feedback', 'none')}"
                ),
                output_model=ReviewDecision,
            )
        except HumanInterventionRequiredError:
            decision = self._fallback_review(state)

        await emit_graph_event(
            "review",
            "reviewer",
            {
                "agent": active_agent,
                "round": current_round,
                "decision": decision.decision,
                "feedback": decision.feedback,
                "confidence": decision.confidence,
            },
        )

        if decision.decision == "approved":
            # 按代理记录通过状态，混合请求才能在最终阶段拼装多个专家结果。
            approved_agents = list(dict.fromkeys(state.get("approved_agents", []) + [active_agent]))
            update = {
                "approved_agents": approved_agents,
                "review_rounds": review_rounds,
                "reviewer_decision": decision.decision,
                "reviewer_feedback": decision.feedback,
            }
            remaining_agents = [agent for agent in state.get("pending_agents", []) if agent not in approved_agents]
            if remaining_agents:
                return Command(goto="dispatch_agent", update=update)
            return Command(goto="finalize", update=update)

        if decision.decision == "revise":
            # 审核反馈写回状态后，下一轮代理执行才能针对性修正结果。
            if current_round >= self.settings.reviewer_max_rounds:
                return self._to_human_command(
                    state,
                    reason=decision.feedback or "Reviewer requested another revision beyond the configured limit.",
                    update={"review_rounds": review_rounds, "reviewer_feedback": decision.feedback},
                )
            goto_node = "knowledge_reasoner" if active_agent == "knowledge" else "gym_agent"
            return Command(
                goto=goto_node,
                update={
                    "review_rounds": review_rounds,
                    "reviewer_decision": decision.decision,
                    "reviewer_feedback": decision.feedback,
                },
            )

        return self._to_human_command(
            state,
            reason=decision.feedback or "Reviewer escalated the result.",
            update={"review_rounds": review_rounds, "reviewer_feedback": decision.feedback},
        )

    async def finalize_node(self, state: AgentState) -> Dict[str, Any]:
        """把已通过审核的专家答案合并成最终回复。"""
        answer_parts: List[str] = []
        if state.get("knowledge_answer"):
            answer_parts.append(state["knowledge_answer"].strip())
        if state.get("location_answer"):
            answer_parts.append(state["location_answer"].strip())

        final_answer = "\n\n".join([part for part in answer_parts if part]).strip()
        await emit_graph_event("final", "finalize", {"answer_length": len(final_answer)})
        return {"final_answer": final_answer}

    async def human_escalation_node(self, state: AgentState) -> Dict[str, Any]:
        """创建人工工单、暂停图执行，并等待人工结果恢复。"""
        reason = state.get("reviewer_feedback") or state.get("last_error") or "Manual intervention required."
        payload = {
            "question": state.get("question"),
            "active_agent": state.get("active_agent"),
            "draft_answer": state.get("draft_answer"),
            "knowledge_hits": state.get("knowledge_hits", [])[:3],
            "nearest_gym": state.get("nearest_gym"),
            "reason": reason,
        }
        ticket_id = await self.human_ticket_repository.create_ticket(
            request_id=state["request_id"],
            thread_id=state["thread_id"],
            active_agent=state.get("active_agent"),
            reason=reason,
            payload=payload,
        )
        await emit_graph_event("interrupt", "human_escalation", {"ticket_id": ticket_id, "reason": reason})
        # LangGraph 的 interrupt 会暂停流程，后续由 API 携带人工结果继续恢复。
        resolution = interrupt(
            {
                "ticket_id": ticket_id,
                "request_id": state["request_id"],
                "thread_id": state["thread_id"],
                "reason": reason,
            }
        )

        resolved_answer = state.get("draft_answer") or state.get("knowledge_answer") or state.get("location_answer") or ""
        note = reason
        if isinstance(resolution, dict):
            resolved_answer = resolution.get("final_answer") or resolved_answer
            note = resolution.get("note") or note
            await self.human_ticket_repository.resolve_ticket(ticket_id, resolution)
        else:
            resolved_answer = str(resolution)
            await self.human_ticket_repository.resolve_ticket(ticket_id, {"final_answer": resolved_answer})

        return {
            "requires_human": True,
            "human_ticket_id": ticket_id,
            "final_answer": resolved_answer,
            "reviewer_decision": "approved_by_human",
            "reviewer_feedback": note,
        }

    def _heuristic_route(self, question: str) -> RoutingDecision:
        """结构化路由模型不可用时使用的兜底路由规则。"""
        lower_question = question.lower()
        knowledge_markers = ["增肌", "减脂", "训练", "饮食", "蛋白", "深蹲", "卧推", "fitness", "muscle"]
        gym_markers = ["健身房", "附近", "导航", "路线", "怎么去", "map", "nearby gym"]

        knowledge_hit = any(token in lower_question for token in knowledge_markers)
        gym_hit = any(token in lower_question for token in gym_markers)

        if knowledge_hit and gym_hit:
            return RoutingDecision(
                intent="hybrid",
                route_reason="问题同时包含健身知识和附近健身房导航需求。",
                rewritten_query=question,
                pending_agents=["knowledge", "gym"],
            )
        if gym_hit:
            return RoutingDecision(
                intent="gym",
                route_reason="问题主要是附近健身房和导航需求。",
                rewritten_query=question,
                pending_agents=["gym"],
            )
        return RoutingDecision(
            intent="knowledge",
            route_reason="默认走健身知识问答链路。",
            rewritten_query=question,
            pending_agents=["knowledge"],
        )

    def _fallback_review(self, state: AgentState) -> ReviewDecision:
        """审核模型不可用时使用的规则型兜底审核逻辑。"""
        active_agent = state.get("active_agent")
        if active_agent == "knowledge" and state.get("knowledge_hits") and state.get("draft_answer"):
            return ReviewDecision(decision="approved", feedback="已通过规则兜底校验。", confidence=0.55)
        if active_agent == "gym" and state.get("nearest_gym") and state.get("draft_answer"):
            return ReviewDecision(decision="approved", feedback="已通过规则兜底校验。", confidence=0.55)
        return ReviewDecision(decision="escalate", feedback="缺少足够证据，建议人工复核。", confidence=0.2)

    def _review_evidence(self, state: AgentState) -> str:
        """整理审核节点需要查看的证据内容。"""
        active_agent = state.get("active_agent")
        if active_agent == "knowledge":
            chunks = [KnowledgeChunk.model_validate(item) for item in state.get("knowledge_hits", [])]
            return self.rag_service.build_context(chunks)
        return json.dumps(
            {
                "user_location": state.get("user_location"),
                "nearest_gym": state.get("nearest_gym"),
            },
            ensure_ascii=False,
        )

    def _fallback_gym_answer(self, user_location: UserLocationRecord, nearest_gym: GymRecord) -> str:
        """在 LLM 不可用时返回规则拼装的健身房答案。"""
        return (
            f"已根据您的IP定位到 {user_location.city or '当前城市'} 附近的最近健身房："
            f"{nearest_gym.name}，距离约 {nearest_gym.distance_km} 公里。"
            f"地址：{nearest_gym.address}。"
            f"可直接点击百度地图导航：{nearest_gym.navigation_url}"
        )

    def _to_human_command(self, state: AgentState, reason: str, update: Dict[str, Any]) -> Command:
        """把错误原因封装成跳转到人工处理节点的命令。"""
        next_update = dict(update)
        next_update["last_error"] = reason
        return Command(goto="human_escalation", update=next_update)
