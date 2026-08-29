"""线索字段合并纯函数（技术方案 §7）。

规则：新值非空且不同 → 覆盖并记 audit；新值为空 → 保留旧值（绝不抹掉已有信息）；
refused_fields 并入 declined_fields；business_email 校验格式，无效丢弃。
"""

import re
from dataclasses import dataclass, field
from typing import Any

from domain.schemas import LeadExtraction

_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")

# 可由提取直接合并的文本字段
MERGEABLE_FIELDS = (
    "name",
    "company",
    "country",
    "business_email",
    "requirement",
    "team_size",
    "budget_range",
    "purchase_timeline",
    "notes",
)

# 追问优先级（§7）：也是 missing_key_fields 的判定范围
KEY_FIELDS = (
    "business_email",
    "company",
    "requirement",
    "team_size",
    "budget_range",
    "purchase_timeline",
)


@dataclass
class MergeResult:
    updates: dict[str, Any] = field(default_factory=dict)
    audit: list[dict[str, Any]] = field(default_factory=list)
    declined_added: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.updates or self.declined_added)


def merge_lead(current: dict[str, Any], extraction: LeadExtraction) -> MergeResult:
    result = MergeResult()

    for field_name in MERGEABLE_FIELDS:
        new_value = getattr(extraction, field_name)
        if new_value is None or not str(new_value).strip():
            continue
        if field_name == "business_email" and not _EMAIL_RE.match(new_value):
            continue  # 无效邮箱丢弃（§7）
        if new_value != current.get(field_name):
            result.updates[field_name] = new_value
            result.audit.append(
                {"field": field_name, "old": current.get(field_name), "new": new_value}
            )

    if extraction.integrations:
        merged = list(
            dict.fromkeys([*(current.get("integrations") or []), *extraction.integrations])
        )
        if merged != (current.get("integrations") or []):
            result.updates["integrations"] = merged
            result.audit.append(
                {"field": "integrations", "old": current.get("integrations"), "new": merged}
            )

    # asked_demo 粘性为真：问过一次 Demo 的事实不会消失
    if extraction.asked_demo_or_quote and not current.get("asked_demo"):
        result.updates["asked_demo"] = True
        result.audit.append({"field": "asked_demo", "old": False, "new": True})
    # freebie_only 跟随最新判断（LLM 基于全量历史评估，用户转为真实意向时应翻回 False）
    if bool(extraction.freebie_only) != bool(current.get("freebie_only")):
        result.updates["freebie_only"] = extraction.freebie_only
        result.audit.append(
            {
                "field": "freebie_only",
                "old": bool(current.get("freebie_only")),
                "new": extraction.freebie_only,
            }
        )

    declined_current = set(current.get("declined_fields") or [])
    result.declined_added = [f for f in extraction.refused_fields if f not in declined_current]

    return result


def missing_key_fields(merged: dict[str, Any], declined: list[str]) -> list[str]:
    """仍缺失且用户未拒绝的关键字段（决定是否追问，§6 extract_lead 第 2 步）。"""
    declined_set = set(declined)
    return [f for f in KEY_FIELDS if f not in declined_set and not str(merged.get(f) or "").strip()]
