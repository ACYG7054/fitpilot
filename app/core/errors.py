"""FitPilot 使用的自定义异常层级。"""

from typing import Any, Dict, Optional


class FitPilotError(Exception):
    """应用内所有自定义异常的基类。"""


class RetryableServiceError(FitPilotError):
    """表示下游依赖异常，但当前场景允许安全重试。"""


class HumanInterventionRequiredError(FitPilotError):
    """表示自动重试已经耗尽，需要人工接手处理。"""

    def __init__(
        self,
        message: str,
        *,
        stage: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.stage = stage
        self.details = details or {}


class McpProtocolError(FitPilotError):
    """表示 MCP 请求或响应不符合协议要求。"""


class JsonOutputParseError(FitPilotError):
    """表示 LLM 返回的 JSON 内容无法被正确解析。"""
