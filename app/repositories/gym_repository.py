"""IP 定位与最近健身房查询相关的仓储层实现。"""

import ipaddress
from typing import Optional

from sqlalchemy import select, text

from app.db.models import IpLocationRange
from app.db.session import Database
from app.models.domain import GymRecord, UserLocationRecord


def ipv4_to_int(ip_value: str) -> int:
    """把 IPv4 字符串转换成 MySQL 中存储的整数形式。"""
    parsed_ip = ipaddress.ip_address(ip_value)
    if getattr(parsed_ip, "version", None) == 6 and getattr(parsed_ip, "ipv4_mapped", None):
        parsed_ip = parsed_ip.ipv4_mapped
    if getattr(parsed_ip, "version", None) != 4:
        raise ValueError("Only IPv4 addresses are supported by the local IP range table.")
    return int(parsed_ip)


class GymRepository:
    """为健身房推荐流程提供只读数据访问能力。"""

    def __init__(self, database: Database) -> None:
        self.database = database

    async def find_user_location_by_ip(self, ip_value: str) -> Optional[UserLocationRecord]:
        """根据本地 IP 区间表解析客户端的大致位置。"""
        ip_num = ipv4_to_int(ip_value)
        async with self.database.session_factory() as session:
            statement = (
                select(IpLocationRange)
                .where(IpLocationRange.ip_start_num <= ip_num)
                .where(IpLocationRange.ip_end_num >= ip_num)
                .limit(1)
            )
            result = await session.execute(statement)
            row = result.scalar_one_or_none()
            if row is None:
                return None

            return UserLocationRecord(
                ip=ip_value,
                province=row.province,
                city=row.city,
                latitude=row.latitude,
                longitude=row.longitude,
            )

    async def find_nearest_gym(self, latitude: float, longitude: float) -> Optional[GymRecord]:
        """通过 MySQL 中的距离计算找出最近的健身房。"""
        async with self.database.session_factory() as session:
            distance_sql = text(
                """
                SELECT
                    id,
                    name,
                    city,
                    address,
                    latitude,
                    longitude,
                    business_hours,
                    tags,
                    6371 * ACOS(
                        LEAST(
                            1,
                            GREATEST(
                                -1,
                                COS(RADIANS(:lat)) * COS(RADIANS(latitude))
                                * COS(RADIANS(longitude) - RADIANS(:lng))
                                + SIN(RADIANS(:lat)) * SIN(RADIANS(latitude))
                            )
                        )
                    ) AS distance_km
                FROM gyms
                ORDER BY distance_km ASC
                LIMIT 1
                """
            )
            # 距离计算下推到 SQL，可以避免先把全部健身房数据拉回 Python 再筛选。
            result = await session.execute(distance_sql, {"lat": latitude, "lng": longitude})
            row = result.mappings().first()
            if row is None:
                return None

            tags = row["tags"] or []
            if not isinstance(tags, list):
                tags = []

            return GymRecord(
                gym_id=int(row["id"]),
                name=row["name"],
                city=row["city"],
                address=row["address"],
                latitude=float(row["latitude"]),
                longitude=float(row["longitude"]),
                distance_km=round(float(row["distance_km"]), 2),
                business_hours=row["business_hours"],
                tags=tags,
            )
