"""Brain：编排层的 LLM 依赖聚合（triage + 受约束回答），实现 domain.orchestrator.Brain 协议。"""

from domain.config import Settings
from domain.schemas import Deadline, RagAnswer, TriageResult
from sqlalchemy.ext.asyncio import AsyncSession

from llm.client import ChatClient, Embedder, build_chat_client, build_embedder
from llm.rag import generate_answer
from llm.triage import run_triage


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
        )


def build_brain(settings: Settings) -> RagBrain | None:
    """缺 key/模型名时返回 None：编排层降级为固定文案 + 通知运营者（安全优先）。"""
    chat = build_chat_client(settings)
    embedder = build_embedder(settings)
    if chat is None or embedder is None:
        return None
    return RagBrain(chat, embedder, settings)
