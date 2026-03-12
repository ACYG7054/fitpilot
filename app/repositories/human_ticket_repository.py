"""人工介入工单的创建与更新仓储。"""

from typing import Any, Dict, Optional

from sqlalchemy import select

from app.db.models import HumanInterventionTicket
from app.db.session import Database


class HumanTicketRepository:
    """负责持久化需要人工处理的工作流中断信息。"""

    def __init__(self, database: Database) -> None:
        self.database = database

    async def create_ticket(
        self,
        *,
        request_id: str,
        thread_id: str,
        active_agent: Optional[str],
        reason: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> int:
        """创建待处理工单并返回数据库主键。"""
        async with self.database.session_factory() as session:
            ticket = HumanInterventionTicket(
                request_id=request_id,
                thread_id=thread_id,
                active_agent=active_agent,
                reason=reason,
                payload=payload or {},
                status="pending",
            )
            session.add(ticket)
            await session.commit()
            await session.refresh(ticket)
            return int(ticket.id)

    async def resolve_ticket(self, ticket_id: int, resolution: Dict[str, Any]) -> None:
        """把工单标记为已解决，并保存人工处理结果。"""
        async with self.database.session_factory() as session:
            result = await session.execute(
                select(HumanInterventionTicket).where(HumanInterventionTicket.id == ticket_id)
            )
            ticket = result.scalar_one_or_none()
            if ticket is None:
                return

            ticket.status = "resolved"
            ticket.resolution = resolution
            await session.commit()
