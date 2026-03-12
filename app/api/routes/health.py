"""运行时健康检查接口。"""

from fastapi import APIRouter, Depends, Request

from app.api.dependencies import get_container
from app.runtime.container import AppContainer


router = APIRouter()


@router.get("/health")
async def healthcheck(request: Request, container: AppContainer = Depends(get_container)) -> dict:
    """返回服务状态以及轻量依赖检查结果。"""
    database_status = "ok"
    chroma_status = "ok"
    database_error = None
    chroma_error = None

    try:
        await container.database.ping()
    except Exception as exc:
        database_status = "error"
        database_error = str(exc)

    try:
        chroma_count = await container.chroma_service.collection_count()
    except Exception as exc:
        chroma_status = "error"
        chroma_error = str(exc)
        chroma_count = 0

    return {
        "service": container.settings.app_name,
        "startup_state": container.startup_state,
        "database": {"status": database_status, "error": database_error},
        "chroma": {"status": chroma_status, "collection_count": chroma_count, "error": chroma_error},
        "openai_enabled": container.settings.openai_enabled,
        "mcp_tools": len(request.app.state.mcp_registry.list_tools()),
    }
