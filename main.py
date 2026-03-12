"""本地开发环境的启动入口。"""

import uvicorn


if __name__ == "__main__":
    # `reload=True` 只适合本地开发热更新，不应直接照搬到生产启动方式。
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
