"""用于处理下游瞬时故障的重试工具。"""

import asyncio
from typing import Awaitable, Callable, Optional, Tuple, Type, TypeVar

from app.core.errors import HumanInterventionRequiredError
from app.core.events import emit_graph_event


T = TypeVar("T")


async def run_with_retry(
    operation_name: str,
    coro_factory: Callable[[], Awaitable[T]],
    *,
    attempts: int,
    base_delay: float,
    retry_on: Tuple[Type[BaseException], ...],
    stage: str,
    on_retry_message: Optional[str] = None,
) -> T:
    """执行异步操作，并在失败时以指数退避方式重试。"""
    last_error: Optional[BaseException] = None
    for attempt in range(1, attempts + 1):
        try:
            return await coro_factory()
        except retry_on as exc:
            last_error = exc
            if attempt >= attempts:
                # 多次重试仍失败时，统一转成需要人工介入的图状态异常。
                raise HumanInterventionRequiredError(
                    str(exc),
                    stage=stage,
                    details={"operation_name": operation_name, "attempts": attempts},
                ) from exc

            await emit_graph_event(
                "retry",
                operation_name,
                {
                    "attempt": attempt,
                    "max_attempts": attempts,
                    "message": on_retry_message or str(exc),
                },
            )
            await asyncio.sleep(base_delay * (2 ** (attempt - 1)))

    raise HumanInterventionRequiredError(
        str(last_error) if last_error else "Unknown retry failure",
        stage=stage,
        details={"operation_name": operation_name, "attempts": attempts},
    )
