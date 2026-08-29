"""线索字段提取调用（§7）。purpose="extract"：非用户路径（30s、重试 1 次、可切 fallback）。"""

import json
from typing import Any

from domain.schemas import LeadExtraction

from llm.client import ChatClient
from llm.prompts import EXTRACTION_SYSTEM

EXTRACT_TIMEOUT_S = 30.0


class LlmLeadExtractor:
    """实现 domain.orchestrator.LeadExtractor 协议。"""

    def __init__(self, chat: ChatClient) -> None:
        self._chat = chat

    async def extract(
        self,
        history: list[dict[str, str]],
        current_lead: dict[str, Any],
        declined_fields: list[str],
    ) -> LeadExtraction:
        system = EXTRACTION_SYSTEM.format(
            current_lead=json.dumps(current_lead, ensure_ascii=False, default=str),
            declined=", ".join(declined_fields) if declined_fields else "(none)",
        )
        messages: list[dict[str, str]] = [{"role": "system", "content": system}, *history[-10:]]
        result = await self._chat.chat(
            messages, purpose="extract", timeout_s=EXTRACT_TIMEOUT_S, schema=LeadExtraction
        )
        assert isinstance(result.parsed, LeadExtraction)
        return result.parsed
