"""同步聊天、流式聊天与人工恢复接口。"""

import asyncio
import contextlib
import json
import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Request
from langgraph.types import Command
from sse_starlette.sse import EventSourceResponse

from app.api.dependencies import get_container
from app.core.events import reset_event_emitter, reset_event_meta, set_event_emitter, set_event_meta
from app.models.api import ChatRequest, ChatResponse, GymRecommendation, HumanResumeRequest, SourceChunk
from app.runtime.container import AppContainer


router = APIRouter()


def _resolve_client_ip(request: Request, explicit_ip: Optional[str]) -> str:
    """从显式参数、代理头或连接信息中解析客户端 IP。"""
    if explicit_ip:
        return explicit_ip

    forwarded_for = request.headers.get("x-forwarded-for", "")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()

    if request.client:
        return request.client.host

    return ""


def _build_initial_state(request_model: ChatRequest, request: Request) -> Dict[str, Any]:
    """根据 HTTP 请求构建 LangGraph 初始状态。"""
    request_id = getattr(request.state, "request_id", None) or uuid.uuid4().hex
    thread_id = request_model.thread_id or uuid.uuid4().hex
    session_id = request_model.session_id or thread_id
    return {
        "session_id": session_id,
        "thread_id": thread_id,
        "request_id": request_id,
        "client_ip": _resolve_client_ip(request, request_model.client_ip),
        "question": request_model.question.strip(),
        "normalized_question": request_model.question.strip(),
    }


def _build_graph_config(thread_id: str) -> Dict[str, Any]:
    """构建带线程检查点键的 LangGraph 运行配置。"""
    return {"configurable": {"thread_id": thread_id}}


def _extract_interrupt_ticket(result: Dict[str, Any]) -> Optional[int]:
    """从 LangGraph 中断结果里提取人工工单编号。"""
    interrupts = result.get("__interrupt__", [])
    if not interrupts:
        return None
    interrupt_payload = getattr(interrupts[0], "value", {}) or {}
    ticket_id = interrupt_payload.get("ticket_id")
    return int(ticket_id) if ticket_id else None


def _serialize_result(result: Dict[str, Any], fallback_state: Dict[str, Any]) -> ChatResponse:
    """把原始图输出整理成对外响应模型。"""
    knowledge_hits = result.get("knowledge_hits", [])
    nearest_gym_payload = result.get("nearest_gym")

    knowledge_sources = [
        SourceChunk(
            chunk_id=item.get("chunk_id", ""),
            title=item.get("title"),
            source=item.get("source"),
            score=float(item.get("rerank_score", 0.0)),
            snippet=item.get("content", "")[:220],
        )
        for item in knowledge_hits
    ]

    nearest_gym = GymRecommendation.model_validate(nearest_gym_payload) if nearest_gym_payload else None

    return ChatResponse(
        session_id=result.get("session_id", fallback_state["session_id"]),
        thread_id=result.get("thread_id", fallback_state["thread_id"]),
        request_id=result.get("request_id", fallback_state["request_id"]),
        intent=result.get("intent", "unknown"),
        answer=(
            result.get("final_answer")
            or result.get("draft_answer")
            or result.get("knowledge_answer")
            or result.get("location_answer")
        ),
        requires_human=bool(result.get("__interrupt__")) or bool(result.get("requires_human", False)),
        human_ticket_id=result.get("human_ticket_id") or _extract_interrupt_ticket(result),
        reviewer_decision=result.get("reviewer_decision"),
        reviewer_feedback=result.get("reviewer_feedback"),
        knowledge_sources=knowledge_sources,
        nearest_gym=nearest_gym,
    )


def _map_langgraph_event(event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """把 LangGraph 回调事件映射成 SSE 事件格式。"""
    event_name = event.get("event")
    node_name = event.get("name")
    if node_name == "LangGraph" and event_name == "on_chain_start":
        return {"event_type": "graph_start", "node": "LangGraph", "data": {}}
    if node_name == "LangGraph" and event_name == "on_chain_end":
        return {"event_type": "graph_end", "node": "LangGraph", "data": {}}
    if event_name == "on_chain_start":
        return {"event_type": "node_start", "node": node_name, "data": {}}
    if event_name == "on_chain_end":
        output = event.get("data", {}).get("output", {})
        data = {"keys": sorted(output.keys())} if isinstance(output, dict) else {}
        return {"event_type": "node_end", "node": node_name, "data": data}
    return None


@router.post("", response_model=ChatResponse)
async def chat(request_model: ChatRequest, request: Request, container: AppContainer = Depends(get_container)) -> ChatResponse:
    """执行一次图流程，并返回最终聊天结果。"""
    initial_state = _build_initial_state(request_model, request)
    result = await container.graph.ainvoke(
        initial_state,
        config=_build_graph_config(initial_state["thread_id"]),
    )
    return _serialize_result(result, initial_state)


@router.post("/stream")
async def chat_stream(
    request_model: ChatRequest,
    request: Request,
    container: AppContainer = Depends(get_container),
) -> EventSourceResponse:
    """通过 SSE 持续推送图执行进度和最终结果。"""
    initial_state = _build_initial_state(request_model, request)
    config = _build_graph_config(initial_state["thread_id"])
    queue: asyncio.Queue = asyncio.Queue()

    async def emit_to_queue(event: Dict[str, Any]) -> None:
        """把自定义图事件写入共享 SSE 队列。"""
        await queue.put(event)

    async def run_graph_stream() -> None:
        """执行图流程，并把所有事件转换成 SSE 负载。"""
        # LangGraph 事件和自定义节点事件共用一个队列，前端就能在单一 SSE 通道里完整渲染过程。
        emitter_token = set_event_emitter(emit_to_queue)
        meta_token = set_event_meta(
            {
                "request_id": initial_state["request_id"],
                "thread_id": initial_state["thread_id"],
                "session_id": initial_state["session_id"],
            }
        )
        try:
            async for event in container.graph.astream_events(initial_state, config=config, version="v2"):
                mapped = _map_langgraph_event(event)
                if mapped:
                    await queue.put(mapped)
                if event.get("event") == "on_chain_end" and event.get("name") == "LangGraph":
                    final_output = event.get("data", {}).get("output", {})
                    await queue.put(
                        {
                            "event_type": "result",
                            "node": "LangGraph",
                            "data": _serialize_result(final_output, initial_state).model_dump(),
                        }
                    )
        except Exception as exc:
            await queue.put({"event_type": "error", "node": "stream", "data": {"message": str(exc)}})
        finally:
            reset_event_emitter(emitter_token)
            reset_event_meta(meta_token)
            await queue.put({"event_type": "done", "node": "stream", "data": {}})
            await queue.put(None)

    task = asyncio.create_task(run_graph_stream())

    async def event_generator():
        """在客户端断开或图结束前，持续产出序列化后的 SSE 事件。"""
        try:
            while True:
                if await request.is_disconnected():
                    break
                item = await queue.get()
                if item is None:
                    break
                yield {
                    "event": item["event_type"],
                    "data": json.dumps(item, ensure_ascii=False),
                }
        finally:
            if not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

    return EventSourceResponse(event_generator())


@router.post("/human-resume/{thread_id}", response_model=ChatResponse)
async def human_resume(
    thread_id: str,
    request_model: HumanResumeRequest,
    request: Request,
    container: AppContainer = Depends(get_container),
) -> ChatResponse:
    """使用人工提供的处理结果恢复先前中断的工作流。"""
    fallback_state = {
        "session_id": thread_id,
        "thread_id": thread_id,
        "request_id": getattr(request.state, "request_id", None) or uuid.uuid4().hex,
    }
    result = await container.graph.ainvoke(
        Command(resume=request_model.model_dump()),
        config=_build_graph_config(thread_id),
    )
    return _serialize_result(result, fallback_state)
