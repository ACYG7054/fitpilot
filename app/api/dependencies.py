"""FastAPI 依赖注入辅助函数。"""

from fastapi import Request

from app.runtime.container import AppContainer


def get_container(request: Request) -> AppContainer:
    """通过 FastAPI 依赖注入暴露应用容器。"""
    return request.app.state.container
