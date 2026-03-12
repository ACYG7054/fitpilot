"""FitPilot 使用的自定义异常层级。"""

from typing import Any, Dict, Optional


class FitPilotError(Exception):
    """Base application error."""


class RetryableServiceError(FitPilotError):
    """Raised when a downstream dependency can be retried safely."""


class HumanInterventionRequiredError(FitPilotError):
    """Raised when automatic retries are exhausted and a human should step in."""

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
    """Raised when an MCP request or response is invalid."""


class JsonOutputParseError(FitPilotError):
    """Raised when LLM JSON output cannot be parsed."""
