"""Pydantic 模型与值对象（技术方案 §6/§7/§12）。"""

import time
from typing import Literal

from pydantic import BaseModel


class Deadline:
    """回复路径端到端预算（§12）：triage 计入总预算，RAG 拿剩余时间。"""

    def __init__(self, seconds: float) -> None:
        self._end = time.monotonic() + seconds

    def remaining(self) -> float:
        return max(0.0, self._end - time.monotonic())

    def exceeded(self) -> bool:
        return self.remaining() <= 0.0


class TriageResult(BaseModel):
    """一次 structured output 调用的联合分类结果（§6 第 3c 步）。"""

    risk: Literal["none", "privacy", "contract", "security", "payment", "complaint"] = "none"
    purchase_intent: bool = False
    needs_rag: bool = True
    language: str = "auto"  # 用户语言代码（如 en/zh）；auto = 未识别，回复跟随用户消息


class RagAnswer(BaseModel):
    """受约束生成结果（§6 第 3d 步）。refused=True 即无答案路径。"""

    refused: bool = False
    text: str | None = None
    source_chunk_ids: list[int] = []
    model_name: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    latency_ms: int | None = None


class PlannedMessage(BaseModel):
    """统一投递的一条待发消息（§6 第 4 步）。delivery_key 是投递幂等键。"""

    delivery_key: str
    text: str
    sender_type: str = "ai"  # ai|system
    answer_status: str | None = None  # answered|refused|handoff
    # LLM 记账与来源（写入 messages 表，§4）
    model_name: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    latency_ms: int | None = None
    source_chunk_ids: list[int] | None = None


class ReplyPlan(BaseModel):
    """路由阶段的唯一产出：只描述要发什么，不执行发送（§6 第 3 步）。"""

    messages: list[PlannedMessage] = []
    final_status: Literal["done", "skipped"] = "done"
    notify_operator: str | None = None  # 需要提醒运营者的文案（可与回复并存）
