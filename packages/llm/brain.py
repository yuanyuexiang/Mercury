"""Brain：编排层的 LLM 依赖聚合（triage / 受约束回答 / CRM 摘要），实现 domain 协议。"""

from domain.config import Settings
from domain.schemas import Deadline, RagAnswer, TriageResult
from sqlalchemy.ext.asyncio import AsyncSession

from llm.client import ChatClient, Embedder, build_chat_client, build_embedder
from llm.prompts import SUMMARY_SYSTEM
from llm.rag import generate_answer
from llm.triage import run_triage

SUMMARY_TIMEOUT_S = 30.0


class RagBrain:
    def __init__(self, chat: ChatClient, embedder: Embedder, settings: Settings) -> None:
        self._chat = chat
        self._embedder = embedder
        self._settings = settings

    async def triage(self, history: list[dict[str, str]], deadline: Deadline) -> TriageResult:
        return await run_triage(self._chat, history, deadline)

    async def answer(
        self,
        session: AsyncSession,
        question: str,
        history: list[dict[str, str]],
        language: str,
        deadline: Deadline,
    ) -> RagAnswer:
        return await generate_answer(
            session,
            self._embedder,
            self._chat,
            question,
            history,
            language,
            deadline,
            top_k=self._settings.rag_top_k,
            min_similarity=self._settings.rag_min_similarity,
            brand_name=self._settings.brand_name,
            tone_hint=self._settings.bot_tone_hint,
        )


class ConversationSummarizer:
    """CRM 摘要（§11）：purpose="summary" 非用户路径（30s、重试、可切 fallback）。"""

    def __init__(self, chat: ChatClient) -> None:
        self._chat = chat

    async def summarize(self, history: list[dict[str, str]]) -> str:
        messages: list[dict[str, str]] = [
            {"role": "system", "content": SUMMARY_SYSTEM},
            *history[-12:],
        ]
        result = await self._chat.chat(messages, purpose="summary", timeout_s=SUMMARY_TIMEOUT_S)
        return (result.content or "").strip()


def build_brain(settings: Settings) -> RagBrain | None:
    """缺 key/模型名时返回 None：编排层降级为固定文案 + 通知运营者（安全优先）。"""
    chat = build_chat_client(settings)
    embedder = build_embedder(settings)
    if chat is None or embedder is None:
        return None
    return RagBrain(chat, embedder, settings)
