"""项目内部使用的轻量 MCP 风格 JSON-RPC 协议实现。"""

import itertools
from typing import Any, Awaitable, Callable, Dict, List, Optional

import httpx
from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.core.config import Settings
from app.core.errors import McpProtocolError
from app.models.domain import McpToolSpec


ToolHandler = Callable[[Dict[str, Any]], Awaitable[Dict[str, Any]]]


class JsonRpcRequest(BaseModel):
    """本地 MCP 路由接收的 JSON-RPC 请求体。"""

    jsonrpc: str = Field(default="2.0")
    id: Optional[Any] = None
    method: str
    params: Dict[str, Any] = Field(default_factory=dict)


class JsonRpcResponse(BaseModel):
    """本地 MCP 路由返回的 JSON-RPC 响应体。"""

    jsonrpc: str = Field(default="2.0")
    id: Optional[Any] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[Dict[str, Any]] = None


class McpToolRegistry:
    """保存 MCP 暴露工具及其异步处理函数的内存注册表。"""

    def __init__(self) -> None:
        self._tools: Dict[str, McpToolSpec] = {}
        self._handlers: Dict[str, ToolHandler] = {}

    def register(self, spec: McpToolSpec, handler: ToolHandler) -> None:
        """注册工具定义以及实际执行该工具的处理函数。"""
        self._tools[spec.name] = spec
        self._handlers[spec.name] = handler

    def list_tools(self) -> List[McpToolSpec]:
        """返回当前已注册的全部工具定义。"""
        return list(self._tools.values())

    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """按名称执行已注册的工具。"""
        handler = self._handlers.get(name)
        if handler is None:
            raise McpProtocolError(f"Unknown MCP tool: {name}")
        return await handler(arguments)


def build_mcp_router(settings: Settings) -> APIRouter:
    """构建暴露本地 MCP 兼容接口的 HTTP 路由。"""
    router = APIRouter()

    @router.post("")
    async def handle_mcp_request(payload: JsonRpcRequest, request: Request) -> JsonRpcResponse:
        registry: McpToolRegistry = request.app.state.mcp_registry

        try:
            if payload.method == "initialize":
                result = {
                    "protocolVersion": settings.mcp_protocol_version,
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": settings.mcp_server_name, "version": "1.0.0"},
                }
            elif payload.method == "tools/list":
                result = {
                    "tools": [
                        {
                            "name": tool.name,
                            "description": tool.description,
                            "inputSchema": tool.input_schema,
                        }
                        for tool in registry.list_tools()
                    ]
                }
            elif payload.method == "tools/call":
                tool_name = payload.params.get("name")
                arguments = payload.params.get("arguments", {})
                content = await registry.call_tool(tool_name, arguments)
                result = {
                    "content": [{"type": "text", "text": str(content)}],
                    "structuredContent": content,
                    "isError": False,
                }
            else:
                raise McpProtocolError(f"Unsupported MCP method: {payload.method}")
        except McpProtocolError as exc:
            return JsonRpcResponse(
                id=payload.id,
                error={"code": -32601, "message": str(exc)},
            )
        except Exception as exc:
            return JsonRpcResponse(
                id=payload.id,
                error={"code": -32000, "message": str(exc)},
            )

        return JsonRpcResponse(id=payload.id, result=result)

    return router


class McpClient:
    """供图节点调用本地 MCP 工具的轻量 JSON-RPC 客户端。"""

    _request_counter = itertools.count(1)

    def __init__(
        self,
        base_url: str,
        timeout_seconds: float,
        app: Optional[Any] = None,
        rpc_path: str = "/mcp",
    ) -> None:
        transport = httpx.ASGITransport(app=app) if app is not None else None
        self.client = httpx.AsyncClient(base_url=base_url, timeout=timeout_seconds, transport=transport)
        self._initialized = False
        self.rpc_path = rpc_path

    async def initialize(self) -> None:
        """执行一次性的 MCP 初始化握手。"""
        if self._initialized:
            return
        await self._call("initialize", {})
        self._initialized = True

    async def list_tools(self) -> List[Dict[str, Any]]:
        """获取 MCP 服务端声明的工具列表。"""
        response = await self._call("tools/list", {})
        return response.get("tools", [])

    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """调用指定工具并返回结构化结果。"""
        await self.initialize()
        # 图节点只感知稳定的工具调用接口，具体协议细节全部收敛在客户端内部。
        response = await self._call("tools/call", {"name": name, "arguments": arguments})
        return response.get("structuredContent", {})

    async def aclose(self) -> None:
        """关闭底层 HTTP 客户端。"""
        await self.client.aclose()

    async def _call(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """发送单次 JSON-RPC 请求，并校验标准 MCP 响应结构。"""
        request_id = next(self._request_counter)
        response = await self.client.post(
            self.rpc_path,
            json={"jsonrpc": "2.0", "id": request_id, "method": method, "params": params},
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("error"):
            raise McpProtocolError(payload["error"]["message"])
        return payload.get("result", {})
