"""健身房、IP 区间与人工介入工单的 ORM 模型定义。"""

from typing import Any, Optional

from sqlalchemy import JSON, BigInteger, DateTime, Float, Integer, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """所有 ORM 实体共用的声明式基类。"""

    pass


class Gym(Base):
    """用于最近健身房查询的健身房记录。"""

    __tablename__ = "gyms"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    city: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    address: Mapped[str] = mapped_column(String(255), nullable=False)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    business_hours: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    tags: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[Any] = mapped_column(DateTime, nullable=False, server_default=func.now())
    updated_at: Mapped[Any] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class IpLocationRange(Base):
    """用于本地定位的 IPv4 区间映射表。"""

    __tablename__ = "ip_location_ranges"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ip_start_num: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    ip_end_num: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    province: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    city: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[Any] = mapped_column(DateTime, nullable=False, server_default=func.now())


class HumanInterventionTicket(Base):
    """保存需要人工审批或修正的工作流工单。"""

    __tablename__ = "human_intervention_tickets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    request_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    thread_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    active_agent: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", server_default="pending")
    reason: Mapped[str] = mapped_column(String(255), nullable=False)
    payload: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)
    resolution: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[Any] = mapped_column(DateTime, nullable=False, server_default=func.now())
    updated_at: Mapped[Any] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
