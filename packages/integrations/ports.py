"""集成端口协议（技术方案 §11）：换 Twenty/HubSpot 只需新增实现，编排层零改动。

canonical row 键（domain.orchestrator.run_sync_lead 组装，实现负责映射到目标系统）：
lead_id, telegram, name, company, country, business_email, requirement, team_size,
budget_range, purchase_timeline, integrations, notes, score, grade, summary,
last_contact, synced_at
"""

from typing import Any, Protocol


class LeadSyncPort(Protocol):
    async def upsert_lead(self, row: dict[str, Any]) -> str:
        """按 row['lead_id'] 幂等 upsert 整行；返回外部标识（如 'row:7' 或记录 ID）。"""
        ...
