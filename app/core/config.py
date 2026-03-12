"""从环境变量和 `.env` 读取应用配置。"""

from functools import lru_cache
from typing import List, Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """全局共享的强类型配置对象。"""

    app_name: str = Field(default="FitPilot", alias="FITPILOT_APP_NAME")
    api_prefix: str = Field(default="/api/v1", alias="FITPILOT_API_PREFIX")
    environment: str = Field(default="dev", alias="FITPILOT_ENVIRONMENT")
    log_level: str = Field(default="INFO", alias="FITPILOT_LOG_LEVEL")

    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    openai_base_url: Optional[str] = Field(default=None, alias="OPENAI_BASE_URL")
    chat_model: str = Field(default="gpt-4.1-mini", alias="FITPILOT_CHAT_MODEL")
    router_model: str = Field(default="gpt-4.1-mini", alias="FITPILOT_ROUTER_MODEL")
    reviewer_model: str = Field(default="gpt-4.1-mini", alias="FITPILOT_REVIEWER_MODEL")
    embedding_model: str = Field(default="text-embedding-3-small", alias="FITPILOT_EMBEDDING_MODEL")
    openai_timeout_seconds: float = Field(default=60.0, alias="FITPILOT_OPENAI_TIMEOUT_SECONDS")
    openai_sdk_retries: int = Field(default=2, alias="FITPILOT_OPENAI_SDK_RETRIES")

    mysql_dsn: str = Field(
        default="mysql+aiomysql://root:password@127.0.0.1:3306/fitpilot?charset=utf8mb4",
        alias="FITPILOT_MYSQL_DSN",
    )
    mysql_echo: bool = Field(default=False, alias="FITPILOT_MYSQL_ECHO")

    chroma_path: str = Field(default="./storage/chroma", alias="FITPILOT_CHROMA_PATH")
    chroma_collection: str = Field(default="fitpilot_knowledge", alias="FITPILOT_CHROMA_COLLECTION")
    rag_top_k: int = Field(default=5, alias="FITPILOT_RAG_TOP_K")
    rag_vector_k: int = Field(default=8, alias="FITPILOT_RAG_VECTOR_K")
    rag_keyword_k: int = Field(default=12, alias="FITPILOT_RAG_KEYWORD_K")
    rag_keyword_limit_per_term: int = Field(default=6, alias="FITPILOT_RAG_KEYWORD_LIMIT_PER_TERM")
    rag_max_context_chars: int = Field(default=3200, alias="FITPILOT_RAG_MAX_CONTEXT_CHARS")

    react_max_rounds: int = Field(default=3, alias="FITPILOT_REACT_MAX_ROUNDS")
    reviewer_max_rounds: int = Field(default=2, alias="FITPILOT_REVIEWER_MAX_ROUNDS")
    service_retry_attempts: int = Field(default=3, alias="FITPILOT_SERVICE_RETRY_ATTEMPTS")
    service_retry_backoff_seconds: float = Field(default=1.0, alias="FITPILOT_SERVICE_RETRY_BACKOFF_SECONDS")

    mcp_protocol_version: str = Field(default="2025-06-18", alias="FITPILOT_MCP_PROTOCOL_VERSION")
    mcp_server_name: str = Field(default="fitpilot-gym-mcp", alias="FITPILOT_MCP_SERVER_NAME")
    mcp_timeout_seconds: float = Field(default=10.0, alias="FITPILOT_MCP_TIMEOUT_SECONDS")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    @property
    def openai_enabled(self) -> bool:
        """返回当前是否已经具备调用 OpenAI 能力的条件。"""
        return bool(self.openai_api_key)

    @property
    def allow_origins(self) -> List[str]:
        """返回 API 允许的跨域来源列表。"""
        return ["*"]


@lru_cache()
def get_settings() -> Settings:
    """缓存配置对象，避免各模块重复解析环境变量。"""
    return Settings()
