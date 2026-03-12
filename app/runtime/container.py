"""负责组装基础设施依赖与图流程对象的应用容器。"""

from dataclasses import dataclass, field
from typing import Any, Dict

from fastapi import FastAPI

from app.core.config import Settings
from app.core.logging import get_logger
from app.db.session import Database
from app.graph.builder import FitPilotGraphFactory
from app.mcp.protocol import McpClient
from app.mcp.tools import register_default_mcp_tools
from app.repositories.gym_repository import GymRepository
from app.repositories.human_ticket_repository import HumanTicketRepository
from app.services.chroma_service import ChromaService
from app.services.gym_service import GymService
from app.services.openai_service import OpenAIService
from app.services.rag_service import RagService


logger = get_logger(__name__)


@dataclass
class AppContainer:
    """在 FastAPI 请求之间复用的长生命周期依赖容器。"""

    settings: Settings
    database: Database
    openai_service: OpenAIService
    chroma_service: ChromaService
    rag_service: RagService
    gym_repository: GymRepository
    gym_service: GymService
    human_ticket_repository: HumanTicketRepository
    mcp_client: McpClient
    graph: Any
    startup_state: Dict[str, Any] = field(default_factory=dict)

    async def startup(self) -> None:
        """执行非阻断式启动检查，并记录检查状态。"""
        # 启动阶段故意保持容错，让 API 能先起来，再通过 `/health` 暴露依赖异常。
        try:
            await self.database.ping()
            self.startup_state["database"] = {"status": "ok", "error": None}
        except Exception as exc:
            self.startup_state["database"] = {"status": "error", "error": str(exc)}
            logger.warning(
                "database_startup_check_failed",
                extra={
                    "component": "app_container",
                    "database_status": "error",
                    "error": str(exc),
                },
            )
        logger.info("container_startup_complete", extra={"component": "app_container"})

    async def shutdown(self) -> None:
        """释放长生命周期的网络客户端和数据库资源。"""
        await self.mcp_client.aclose()
        await self.database.dispose()


def build_container(app: FastAPI, settings: Settings) -> AppContainer:
    """实例化基础设施服务，并编译 LangGraph 工作流。"""
    # 容器集中管理重量级客户端，保证路由与图节点在整个进程生命周期内复用同一套资源。
    database = Database(settings)
    openai_service = OpenAIService(settings)
    chroma_service = ChromaService(settings, openai_service)
    rag_service = RagService(chroma_service, settings)
    gym_repository = GymRepository(database)
    gym_service = GymService(gym_repository)
    human_ticket_repository = HumanTicketRepository(database)

    register_default_mcp_tools(app.state.mcp_registry, gym_service)
    mcp_client = McpClient(base_url="http://fitpilot.local", timeout_seconds=settings.mcp_timeout_seconds, app=app)
    graph = FitPilotGraphFactory(
        settings=settings,
        openai_service=openai_service,
        rag_service=rag_service,
        mcp_client=mcp_client,
        human_ticket_repository=human_ticket_repository,
    ).build()

    return AppContainer(
        settings=settings,
        database=database,
        openai_service=openai_service,
        chroma_service=chroma_service,
        rag_service=rag_service,
        gym_repository=gym_repository,
        gym_service=gym_service,
        human_ticket_repository=human_ticket_repository,
        mcp_client=mcp_client,
        graph=graph,
    )
