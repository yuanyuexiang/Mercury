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
    "Channel",
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
    "source_channel",
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

    def probe(self) -> str:
        """连接自检（后台「测试」用）：打开表、确保 Leads 工作表与表头就绪，返回表格标题。"""
        import gspread

        client = gspread.service_account_from_dict(self._credentials)
        spreadsheet = client.open_by_key(self._spreadsheet_id)
        try:
            ws = spreadsheet.worksheet(self._worksheet_title)
        except Exception:
            ws = spreadsheet.add_worksheet(self._worksheet_title, rows=1000, cols=len(HEADERS))
        if ws.row_values(1) != HEADERS:
            ws.update(values=[HEADERS], range_name="A1")
        return str(spreadsheet.title)

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


def parse_service_account(raw: str) -> dict[str, Any]:
    """解析 service account 凭据：原始 JSON（后台粘贴）/ 文件路径 / base64 三种形态。

    解析失败抛 ValueError（调用方决定是拒绝保存还是走 retry）。
    """
    raw = raw.strip()
    try:
        if raw.startswith("{"):
            return json.loads(raw)  # type: ignore[no-any-return]
        if Path(raw).exists():
            return json.loads(Path(raw).read_text(encoding="utf-8"))  # type: ignore[no-any-return]
        return json.loads(base64.b64decode(raw))  # type: ignore[no-any-return]
    except Exception as exc:
        raise ValueError(
            "service account JSON 无法解析（支持原始 JSON / 文件路径 / base64）"
        ) from exc


class DynamicLeadSync:
    """每次调用解析 Sheets 配置的 LeadSyncPort（后台「系统设置」可配，DB 优先 env 兜底）。

    未配置时抛 RuntimeError → 同步任务走 retry 并在超限后通知运营者（§11 语义不变）；
    后台配好凭据即自动恢复，不需要重启。配置变更时重建底层客户端。
    """

    def __init__(self, store: Any) -> None:  # AppSettingsStore（避免循环 import 用 Any）
        self._store = store
        self._cached_key: tuple[str, str] | None = None
        self._impl: GoogleSheetsLeadSync | None = None

    async def upsert_lead(self, row: dict[str, Any]) -> str:
        raw = await self._store.sheets_service_account_json()
        spreadsheet_id = await self._store.leads_spreadsheet_id()
        if not raw or not spreadsheet_id:
            raise RuntimeError(
                "google_sheets 未配置（后台「系统设置 → Google Sheets 同步」，或 env 兜底）"
            )
        key = (raw, spreadsheet_id)
        if key != self._cached_key or self._impl is None:
            self._impl = GoogleSheetsLeadSync(parse_service_account(raw), spreadsheet_id)
            self._cached_key = key
            logger.info("lead_sync_rebuilt", spreadsheet_id=spreadsheet_id[:8])
        return await self._impl.upsert_lead(row)


def build_lead_sync(settings: Settings) -> GoogleSheetsLeadSync | None:
    """env 直连构建（脚本/测试用）；生产走 DynamicLeadSync。"""
    raw = settings.google_service_account_json
    if not raw or not settings.leads_spreadsheet_id:
        return None
    try:
        credentials = parse_service_account(raw)
    except ValueError:
        logger.error("google_service_account_json_invalid")
        return None
    return GoogleSheetsLeadSync(credentials, settings.leads_spreadsheet_id)
