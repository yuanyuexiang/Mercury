"""LLM 客户端（技术方案 §12）：embedding + chat（双档超时策略、schema 降级、记账）。

DbConfigSource（后台配置供应商）在 M8 接入；当前为 env 配置。
"""

import asyncio
import hashlib
import json
import math
import time
from dataclasses import dataclass
from typing import Any, Protocol, TypeVar

import structlog
from domain.config import Settings
from openai import AsyncOpenAI, BadRequestError
from pydantic import BaseModel

from llm.prompts import JSON_FALLBACK_SUFFIX

logger = structlog.get_logger()

EMBED_BATCH_SIZE = 64

# 用户回复路径的 purpose：不重试、不切 fallback，失败立即降级（§12）
USER_PATH_PURPOSES = ("triage", "rag")

T = TypeVar("T", bound=BaseModel)


class LLMOutputError(Exception):
    """结构化输出经修复重试后仍不合法。"""


@dataclass
class ChatResult:
    content: str | None
    parsed: BaseModel | None
    model_name: str
    prompt_tokens: int | None
    completion_tokens: int | None
    latency_ms: int


class ChatClient(Protocol):
    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        purpose: str,
        timeout_s: float,
        schema: type[BaseModel] | None = None,
    ) -> ChatResult: ...


class OpenAIChatClient:
    """OpenAI 兼容 chat 端点。

    非用户路径（extract/summary/索引）：同模型重试 1 次，连续失败切 fallback 模型；
    用户路径（triage/rag）：单次调用，失败直接抛给编排层降级。
    supports_json_schema=False 的端点降级为 json_object + 提示词约束，仍过 Pydantic 校验。
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        fallback_model: str = "",
        supports_json_schema: bool = True,
    ) -> None:
        self._client = AsyncOpenAI(base_url=base_url, api_key=api_key)
        self._model = model
        self._fallback_model = fallback_model
        self._supports_json_schema = supports_json_schema

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        purpose: str,
        timeout_s: float,
        schema: type[BaseModel] | None = None,
    ) -> ChatResult:
        if purpose in USER_PATH_PURPOSES:
            attempts = [self._model]
        else:
            attempts = [self._model, self._model]
            if self._fallback_model:
                attempts.append(self._fallback_model)

        last_error: Exception | None = None
        for model in attempts:
            try:
                async with asyncio.timeout(timeout_s):
                    return await self._call(model, messages, purpose, schema)
            except Exception as exc:  # 超时/网络/校验失败统一按一次尝试计
                last_error = exc
                logger.warning("llm_chat_attempt_failed", purpose=purpose, model=model)
        assert last_error is not None
        raise last_error

    async def _call(
        self,
        model: str,
        messages: list[dict[str, str]],
        purpose: str,
        schema: type[BaseModel] | None,
    ) -> ChatResult:
        began = time.monotonic()
        parsed: BaseModel | None = None
        content: str | None = None
        usage: Any = None

        if schema is not None and self._supports_json_schema:
            parsed_completion = await self._client.chat.completions.parse(
                model=model,
                messages=messages,  # type: ignore[arg-type]
                response_format=schema,
            )
            message = parsed_completion.choices[0].message
            if message.parsed is None:
                raise LLMOutputError(f"structured output 为空（refusal: {message.refusal!r}）")
            parsed = message.parsed
            content = message.content
            usage = parsed_completion.usage
        elif schema is not None:
            fallback_messages = [
                *messages,
                {
                    "role": "system",
                    "content": JSON_FALLBACK_SUFFIX.format(
                        schema=json.dumps(schema.model_json_schema(), ensure_ascii=False)
                    ),
                },
            ]
            completion = await self._client.chat.completions.create(
                model=model,
                messages=fallback_messages,  # type: ignore[arg-type]
                response_format={"type": "json_object"},  # type: ignore[call-overload]
            )
            raw = completion.choices[0].message.content or ""
            try:
                parsed = schema.model_validate(json.loads(raw))
            except Exception as exc:
                raise LLMOutputError(f"json_object 降级输出不合法: {raw[:200]}") from exc
            content = raw
            usage = completion.usage
        else:
            completion = await self._client.chat.completions.create(
                model=model,
                messages=messages,  # type: ignore[arg-type]
            )
            content = completion.choices[0].message.content
            usage = completion.usage

        result = ChatResult(
            content=content,
            parsed=parsed,
            model_name=model,
            prompt_tokens=usage.prompt_tokens if usage else None,
            completion_tokens=usage.completion_tokens if usage else None,
            latency_ms=int((time.monotonic() - began) * 1000),
        )
        logger.info(
            "llm_chat_completed",
            purpose=purpose,
            model=model,
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            latency_ms=result.latency_ms,
        )
        return result


class Embedder(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class OpenAIEmbedder:
    """OpenAI 兼容 embedding 端点；批量调用并记录耗时（§12 记账要求）。

    dimensions：向 Matryoshka 模型（如 Qwen3-Embedding 系列，原生维度非 1536）请求
    定制输出维度；上游拒绝该参数时自动降级为不带参重试并记住结论
    （原生 1536 维模型两种调法结果一致）。维度守卫在调用方兜底。
    """

    def __init__(
        self, base_url: str, api_key: str, model: str, dimensions: int | None = None
    ) -> None:
        self._client = AsyncOpenAI(base_url=base_url, api_key=api_key)
        self._model = model
        self._dimensions = dimensions
        self._dimensions_rejected = False

    async def _create(self, batch: list[str]) -> Any:
        if self._dimensions is not None and not self._dimensions_rejected:
            try:
                return await self._client.embeddings.create(
                    model=self._model, input=batch, dimensions=self._dimensions
                )
            except BadRequestError:
                logger.info("embed_dimensions_rejected_retry_without", model=self._model)
                self._dimensions_rejected = True
        return await self._client.embeddings.create(model=self._model, input=batch)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), EMBED_BATCH_SIZE):
            batch = texts[start : start + EMBED_BATCH_SIZE]
            began = time.monotonic()
            resp = await self._create(batch)
            logger.info(
                "embeddings_created",
                model=self._model,
                count=len(batch),
                latency_ms=int((time.monotonic() - began) * 1000),
                prompt_tokens=resp.usage.prompt_tokens if resp.usage else None,
            )
            ordered = sorted(resp.data, key=lambda item: item.index)
            vectors.extend(item.embedding for item in ordered)
        return vectors


class DeterministicFakeEmbedder:
    """离线/测试替身：同文本恒同向量（单位化），不同文本近似正交——无语义，仅用于管线冒烟与测试。"""

    def __init__(self, dim: int = 1536) -> None:
        self._dim = dim

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(t) for t in texts]

    def _vector(self, text: str) -> list[float]:
        values: list[float] = []
        seed = text.encode("utf-8")
        counter = 0
        while len(values) < self._dim:
            digest = hashlib.sha256(seed + counter.to_bytes(4, "big")).digest()
            values.extend(b / 255.0 - 0.5 for b in digest)
            counter += 1
        vec = values[: self._dim]
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]


def build_embedder(settings: Settings) -> OpenAIEmbedder | None:
    """无 LLM_API_KEY 时返回 None：索引任务会明确失败，绝不静默用假向量污染知识库。"""
    if settings.llm_api_key:
        from domain.models import EMBEDDING_DIM

        return OpenAIEmbedder(
            settings.llm_base_url,
            settings.llm_api_key,
            settings.llm_embed_model,
            dimensions=EMBEDDING_DIM,
        )
    return None


def build_chat_client(settings: Settings) -> OpenAIChatClient | None:
    if settings.llm_api_key and settings.llm_chat_model:
        return OpenAIChatClient(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            model=settings.llm_chat_model,
            fallback_model=settings.llm_chat_model_fallback,
        )
    return None


async def list_models(base_url: str, api_key: str, timeout_s: float = 10.0) -> list[str]:
    """拉取 OpenAI 兼容接口的可用模型列表（GET /models）。

    后台「模型配置」用：贴上 key 即可下拉选模型，不用查文档手填模型名。
    """
    import httpx

    url = base_url.rstrip("/") + "/models"
    async with httpx.AsyncClient(timeout=timeout_s) as client:
        resp = await client.get(url, headers={"Authorization": f"Bearer {api_key}"})
        resp.raise_for_status()
        data = resp.json()
    items = data.get("data", []) if isinstance(data, dict) else []
    ids = [m["id"] for m in items if isinstance(m, dict) and isinstance(m.get("id"), str)]
    return sorted(ids)
