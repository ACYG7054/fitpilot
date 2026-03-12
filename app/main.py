"""FastAPI 应用工厂、中间件与路由注册入口。"""

import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.chat import router as chat_router
from app.api.routes.health import router as health_router
from app.api.routes.knowledge import router as knowledge_router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.mcp.protocol import McpToolRegistry, build_mcp_router
from app.runtime.container import build_container


def create_app() -> FastAPI:
    """创建并配置 FastAPI 应用实例。"""
    settings = get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # 先创建 MCP 注册表，这样应用生命周期内本地 MCP 路由就能立即提供工具能力。
        app.state.mcp_registry = McpToolRegistry()
        container = build_container(app, settings)
        app.state.container = container
        await container.startup()
        try:
            yield
        finally:
            await container.shutdown()

    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allow_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def request_trace_middleware(request: Request, call_next):
        # 为每个请求分配稳定的 request id，便于串联日志、图事件和 SSE 推送。
        request.state.request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        response = await call_next(request)
        response.headers["x-request-id"] = request.state.request_id
        return response

    app.include_router(health_router)
    app.include_router(chat_router, prefix=f"{settings.api_prefix}/chat", tags=["chat"])
    app.include_router(knowledge_router, prefix=f"{settings.api_prefix}/knowledge", tags=["knowledge"])
    app.include_router(build_mcp_router(settings), prefix="/mcp", tags=["mcp"])
    return app


app = create_app()
