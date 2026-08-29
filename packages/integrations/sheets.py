"""Google Sheets 的 LeadSyncPort 实现（技术方案 §11）：按 Lead ID 列查行，有则整行更新无则 append。

gspread 是同步库，统一经 asyncio.to_thread 调用，不阻塞 worker 事件循环。
"""

import asyncio
import base64
import json
from pathlib import Path
from typing import Any

import structlog
from domain.config import Settings

logger = structlog.get_logger()

HEADERS = [
    "Lead ID",
    "Telegram",
    "Name",
    "Company",
    "Country",
    "Email",
    "Requirement",
    "Team Size",
    "Budget",
    "Timeline",
    "Integrations",
    "Notes",
    "Score",
    "Grade",
    "Summary",
    "Last Contact",
    "Synced At",
]

# 与 HEADERS 一一对应的 canonical row 键（见 ports.py）
FIELD_KEYS = [
    "lead_id",
    "telegram",
    "name",
    "company",
    "country",
    "business_email",
    "requirement",
    "team_size",
    "budget_range",
    "purchase_timeline",
    "integrations",
    "notes",
    "score",
    "grade",
    "summary",
    "last_contact",
    "synced_at",
]


class GoogleSheetsLeadSync:
    def __init__(
        self, credentials: dict[str, Any], spreadsheet_id: str, worksheet_title: str = "Leads"
    ) -> None:
        self._credentials = credentials
        self._spreadsheet_id = spreadsheet_id
        self._worksheet_title = worksheet_title
        self._ws: Any = None  # 惰性初始化，进程内复用

    async def upsert_lead(self, row: dict[str, Any]) -> str:
        return await asyncio.to_thread(self._upsert, row)

    def _worksheet(self) -> Any:
        if self._ws is None:
            import gspread

            client = gspread.service_account_from_dict(self._credentials)
            spreadsheet = client.open_by_key(self._spreadsheet_id)
            try:
                self._ws = spreadsheet.worksheet(self._worksheet_title)
            except Exception:
                self._ws = spreadsheet.add_worksheet(
                    self._worksheet_title, rows=1000, cols=len(HEADERS)
                )
            if self._ws.row_values(1) != HEADERS:
                self._ws.update(values=[HEADERS], range_name="A1")
        return self._ws

    def _upsert(self, row: dict[str, Any]) -> str:
        ws = self._worksheet()
        values = [str(row.get(key, "") or "") for key in FIELD_KEYS]
        lead_id = str(row["lead_id"])

        cell = None
        try:
            cell = ws.find(lead_id, in_column=1)
        except Exception:  # 旧版 gspread 找不到时抛 CellNotFound
            cell = None

        if cell is not None:
            ws.update(values=[values], range_name=f"A{cell.row}")
            row_number = cell.row
        else:
            result = ws.append_row(values, value_input_option="RAW")
            # updatedRange 形如 "Leads!A7:Q7"
            updated_range = result.get("updates", {}).get("updatedRange", "")
            row_number = int("".join(filter(str.isdigit, updated_range.split(":")[0])) or 0)
        logger.info("sheet_lead_upserted", lead_id=lead_id, row=row_number)
        return f"row:{row_number}"


def build_lead_sync(settings: Settings) -> GoogleSheetsLeadSync | None:
    """凭据或表 ID 未配置时返回 None：同步任务明确失败并通知运营者。"""
    raw = settings.google_service_account_json
    if not raw or not settings.leads_spreadsheet_id:
        return None
    try:
        if Path(raw).exists():
            credentials = json.loads(Path(raw).read_text(encoding="utf-8"))
        else:
            credentials = json.loads(base64.b64decode(raw))
    except Exception:
        logger.error("google_service_account_json_invalid")
        return None
    return GoogleSheetsLeadSync(credentials, settings.leads_spreadsheet_id)
