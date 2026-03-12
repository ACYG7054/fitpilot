"""项目统一使用的结构化日志工具。"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict

import orjson


class JsonFormatter(logging.Formatter):
    """将日志记录序列化为便于采集的 JSON 行。"""

    reserved_fields = {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "module",
        "msecs",
        "message",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "thread",
        "threadName",
    }

    def format(self, record: logging.LogRecord) -> str:
        """把标准日志记录转换为 JSON 字符串。"""
        payload: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key in self.reserved_fields or key.startswith("_"):
                continue
            payload[key] = value

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return orjson.dumps(payload).decode("utf-8")


def configure_logging(level: str) -> None:
    """使用项目定义的 JSON Formatter 重置根日志器。"""
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(level.upper())

    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root_logger.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    """返回指定模块名对应的日志器。"""
    return logging.getLogger(name)
