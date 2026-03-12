"""数据库引擎与会话工厂的封装。"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import Settings


class Database:
    """对异步 SQLAlchemy 引擎和会话工厂的轻量封装。"""

    def __init__(self, settings: Settings) -> None:
        self.engine = create_async_engine(
            settings.mysql_dsn,
            echo=settings.mysql_echo,
            pool_pre_ping=True,
            pool_recycle=1800,
        )
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False, class_=AsyncSession)

    async def ping(self) -> None:
        """执行轻量查询，验证数据库连接是否可用。"""
        async with self.session_factory() as session:
            await session.execute(text("SELECT 1"))

    async def dispose(self) -> None:
        """关闭底层数据库引擎与连接池。"""
        await self.engine.dispose()
