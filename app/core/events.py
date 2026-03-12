"""为图执行和 SSE 跟踪提供上下文级事件发送器。"""

from contextvars import ContextVar, Token
from datetime import datetime, timezone
from inspect import isawaitable
from typing import Any, Callable, Dict, Optional

from app.core.logging import get_logger


logger = get_logger(__name__)

EventEmitter = Callable[[Dict[str, Any]], Any]

_event_emitter_var: ContextVar[Optional[EventEmitter]] = ContextVar("fitpilot_event_emitter", default=None)
_event_meta_var: ContextVar[Dict[str, Any]] = ContextVar("fitpilot_event_meta", default={})


def set_event_emitter(emitter: Optional[EventEmitter]) -> Token:
    """给当前异步上下文绑定事件接收器。"""
    return _event_emitter_var.set(emitter)


def reset_event_emitter(token: Token) -> None:
    """在请求结束后恢复之前的事件接收器。"""
    _event_emitter_var.reset(token)


def set_event_meta(meta: Dict[str, Any]) -> Token:
    """给当前上下文中的所有事件附加共享元数据。"""
    return _event_meta_var.set(meta)


def reset_event_meta(token: Token) -> None:
    """恢复之前的事件元数据配置。"""
    _event_meta_var.reset(token)


async def emit_graph_event(event_type: str, node: str, payload: Optional[Dict[str, Any]] = None) -> None:
    """把图事件同时写入日志，并投递给可选的内存事件接收器。"""
    event: Dict[str, Any] = {
        "event_type": event_type,
        "node": node,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data": payload or {},
    }
    event.update(_event_meta_var.get())
    logger.info("graph_event", extra=event)

    emitter = _event_emitter_var.get()
    if emitter is None:
        return

    result = emitter(event)
    if isawaitable(result):
        await result
