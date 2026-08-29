"""意图/风险/是否需 RAG 联合分类（技术方案 §6 第 3c 步）：一次 structured output 调用。"""

from domain.schemas import Deadline, TriageResult

from llm.client import ChatClient
from llm.prompts import TRIAGE_SYSTEM

TRIAGE_TIMEOUT_CAP_S = 2.0


async def run_triage(
    chat: ChatClient, history: list[dict[str, str]], deadline: Deadline
) -> TriageResult:
    """失败/超时由调用方降级为默认值（needs_rag=True, risk=none），此处只管调用。"""
    timeout = min(TRIAGE_TIMEOUT_CAP_S, deadline.remaining())
    if timeout <= 0.1:
        raise TimeoutError("triage 预算耗尽")
    messages: list[dict[str, str]] = [{"role": "system", "content": TRIAGE_SYSTEM}, *history[-6:]]
    result = await chat.chat(messages, purpose="triage", timeout_s=timeout, schema=TriageResult)
    assert isinstance(result.parsed, TriageResult)
    return result.parsed
