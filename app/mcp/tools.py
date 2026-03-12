"""图流程默认使用的内置 MCP 工具注册逻辑。"""

from typing import Any, Dict

from app.mcp.protocol import McpToolRegistry
from app.models.domain import GymRecord, McpToolSpec, UserLocationRecord
from app.services.gym_service import GymService


def register_default_mcp_tools(registry: McpToolRegistry, gym_service: GymService) -> None:
    """注册默认的健身房查询与导航链接工具。"""
    async def find_nearest_gym(arguments: Dict[str, Any]) -> Dict[str, Any]:
        client_ip = arguments.get("client_ip", "")
        return await gym_service.find_nearest_gym_by_ip(client_ip)

    async def build_navigation_url(arguments: Dict[str, Any]) -> Dict[str, Any]:
        user_location = UserLocationRecord.model_validate(arguments.get("user_location", {}))
        gym = GymRecord.model_validate(arguments.get("nearest_gym", {}))
        return {
            "navigation_url": gym_service.build_baidu_navigation_url(user_location, gym),
        }

    registry.register(
        McpToolSpec(
            name="find_nearest_gym",
            description="Lookup the nearest gym from the local MySQL gym table by client IPv4 address.",
            input_schema={
                "type": "object",
                "properties": {
                    "client_ip": {"type": "string", "description": "Client IPv4 address."},
                },
                "required": ["client_ip"],
            },
        ),
        find_nearest_gym,
    )

    registry.register(
        McpToolSpec(
            name="build_baidu_navigation_url",
            description="Build a Baidu Map navigation URL using the user location and nearest gym coordinates.",
            input_schema={
                "type": "object",
                "properties": {
                    "user_location": {"type": "object"},
                    "nearest_gym": {"type": "object"},
                },
                "required": ["user_location", "nearest_gym"],
            },
        ),
        build_navigation_url,
    )
