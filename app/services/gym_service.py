"""基于位置的健身房推荐与导航链接服务。"""

from typing import Any, Dict
from urllib.parse import quote

from app.core.errors import HumanInterventionRequiredError
from app.models.domain import GymRecord, UserLocationRecord
from app.repositories.gym_repository import GymRepository


class GymService:
    """协调仓储查询，并组装面向上层的健身房结果。"""

    def __init__(self, repository: GymRepository) -> None:
        self.repository = repository

    async def find_nearest_gym_by_ip(self, client_ip: str) -> Dict[str, Any]:
        """根据客户端 IP 解析位置，并查询最近的健身房。"""
        user_location = await self.repository.find_user_location_by_ip(client_ip)
        if user_location is None:
            raise HumanInterventionRequiredError(
                "The local IP range table does not contain the client IP.",
                stage="gym_lookup",
                details={"client_ip": client_ip},
            )

        nearest_gym = await self.repository.find_nearest_gym(user_location.latitude, user_location.longitude)
        if nearest_gym is None:
            raise HumanInterventionRequiredError(
                "No gym records were found in the local gym table.",
                stage="gym_lookup",
                details={"client_ip": client_ip},
            )

        return {
            "user_location": user_location.model_dump(),
            "nearest_gym": nearest_gym.model_dump(),
        }

    @staticmethod
    def build_baidu_navigation_url(user_location: UserLocationRecord, gym: GymRecord) -> str:
        """生成从用户位置前往目标健身房的百度导航链接。"""
        origin_name = quote("Current Location")
        destination_name = quote(gym.name)
        return (
            "https://api.map.baidu.com/direction?"
            f"origin=latlng:{user_location.latitude},{user_location.longitude}|name:{origin_name}"
            f"&destination=latlng:{gym.latitude},{gym.longitude}|name:{destination_name}"
            "&mode=driving"
            f"&region={quote(gym.city)}"
            "&output=html"
            "&coord_type=wgs84ll"
            "&src=fitpilot.demo"
        )
