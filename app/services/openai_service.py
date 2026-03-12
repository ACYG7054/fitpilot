"""封装 OpenAI 调用、流式输出、向量生成与 JSON 解析。"""

import json
import re
from typing import Any, Callable, Dict, List, Optional, Type, TypeVar

import httpx
from openai import APIConnectionError, APITimeoutError, AsyncOpenAI, InternalServerError, RateLimitError
from pydantic import BaseModel, ValidationError

from app.core.config import Settings
from app.core.errors import HumanInterventionRequiredError, JsonOutputParseError
from app.core.retry import run_with_retry


T = TypeVar("T", bound=BaseModel)

RETRYABLE_OPENAI_ERRORS = (
    APIConnectionError,
    APITimeoutError,
    InternalServerError,
    RateLimitError,
    httpx.HTTPError,
)

JSON_BLOCK_PATTERN = re.compile(r"```json\s*(.*?)\s*```", re.DOTALL)


class OpenAIService:
    """基于项目需求对 OpenAI SDK 做统一包装。"""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = AsyncOpenAI(
            api_key=settings.openai_api_key or "missing-api-key",
            base_url=settings.openai_base_url,
            timeout=settings.openai_timeout_seconds,
            max_retries=settings.openai_sdk_retries,
        )

    def _ensure_api_key(self) -> None:
        """在缺少凭证时尽早失败，避免继续执行下游逻辑。"""
        if not self.settings.openai_enabled:
            raise HumanInterventionRequiredError(
                "OPENAI_API_KEY is missing.",
                stage="openai_configuration",
                details={"hint": "Configure OPENAI_API_KEY in .env before calling the LLM."},
            )

    @staticmethod
    def _extract_json(raw_text: str) -> Dict[str, Any]:
        """把模型原始输出解析成 JSON 对象，兼容代码块包裹格式。"""
        text = raw_text.strip()
        match = JSON_BLOCK_PATTERN.search(text)
        if match:
            text = match.group(1).strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise JsonOutputParseError(str(exc)) from exc

    async def chat_json(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        output_model: Type[T],
        temperature: float = 0.2,
    ) -> T:
        """请求结构化 JSON 输出，并校验成指定的 Pydantic 模型。"""
        self._ensure_api_key()

        async def _call() -> T:
            # 路由、推理、审核节点使用 JSON 模式，便于图内控制流保持确定性。
            completion = await self.client.chat.completions.create(
                model=model,
                temperature=temperature,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
            content = completion.choices[0].message.content or "{}"
            payload = self._extract_json(content)
            try:
                return output_model.model_validate(payload)
            except ValidationError as exc:
                raise JsonOutputParseError(str(exc)) from exc

        return await run_with_retry(
            "openai_chat_json",
            _call,
            attempts=self.settings.service_retry_attempts,
            base_delay=self.settings.service_retry_backoff_seconds,
            retry_on=RETRYABLE_OPENAI_ERRORS,
            stage="llm_json",
        )

    async def chat_text(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.3,
        max_tokens: int = 1200,
    ) -> str:
        """请求普通的非流式文本补全。"""
        self._ensure_api_key()

        async def _call() -> str:
            completion = await self.client.chat.completions.create(
                model=model,
                temperature=temperature,
                max_completion_tokens=max_tokens,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
            return completion.choices[0].message.content or ""

        return await run_with_retry(
            "openai_chat_text",
            _call,
            attempts=self.settings.service_retry_attempts,
            base_delay=self.settings.service_retry_backoff_seconds,
            retry_on=RETRYABLE_OPENAI_ERRORS,
            stage="llm_text",
        )

    async def stream_text(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        on_token: Optional[Callable[[str], Any]] = None,
        temperature: float = 0.3,
        max_tokens: int = 1200,
    ) -> str:
        """流式接收文本 token，并同时累积完整回复内容。"""
        self._ensure_api_key()

        async def _call() -> str:
            full_text: List[str] = []
            # token 流通过图节点提供的回调继续转发到 SSE 队列。
            stream = await self.client.chat.completions.create(
                model=model,
                temperature=temperature,
                max_completion_tokens=max_tokens,
                stream=True,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
            async for chunk in stream:
                delta = chunk.choices[0].delta.content or ""
                if not delta:
                    continue
                full_text.append(delta)
                if on_token is not None:
                    result = on_token(delta)
                    if hasattr(result, "__await__"):
                        await result
            return "".join(full_text)

        return await run_with_retry(
            "openai_stream_text",
            _call,
            attempts=self.settings.service_retry_attempts,
            base_delay=self.settings.service_retry_backoff_seconds,
            retry_on=RETRYABLE_OPENAI_ERRORS,
            stage="llm_stream",
        )

    async def embed_texts(self, texts: List[str]) -> List[List[float]]:
        """为一段或多段文本生成向量。"""
        self._ensure_api_key()

        async def _call() -> List[List[float]]:
            # 这里直接使用 OpenAI SDK 生成向量，保证项目只维护一套模型提供方接口。
            response = await self.client.embeddings.create(
                model=self.settings.embedding_model,
                input=texts,
            )
            return [item.embedding for item in response.data]

        return await run_with_retry(
            "openai_embeddings",
            _call,
            attempts=self.settings.service_retry_attempts,
            base_delay=self.settings.service_retry_backoff_seconds,
            retry_on=RETRYABLE_OPENAI_ERRORS,
            stage="embedding",
        )
