"""线索评分：纯函数、表驱动规则（技术方案 §8）。

LLM 只负责提取事实，评分完全确定性、可解释（§9.1）；
命中的规则名存入 score_reasons，后台原样展示。
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

# 免费邮箱域（§8）：可按客户配置扩展
FREE_EMAIL_DOMAINS = {
    "gmail.com",
    "googlemail.com",
    "outlook.com",
    "hotmail.com",
    "live.com",
    "yahoo.com",
    "icloud.com",
    "me.com",
    "qq.com",
    "163.com",
    "126.com",
    "foxmail.com",
    "sina.com",
    "proton.me",
    "protonmail.com",
    "mail.com",
    "gmx.com",
    "aol.com",
    "yandex.com",
}

# 团队规模达标下限（ICP：≥2 名客服/运营、月 300+ 咨询的团队，§8"达到目标客户标准"）
TEAM_SIZE_FIT_MIN = 10

GRADE_LOW_MAX = 29
GRADE_MEDIUM_MAX = 59

# 30 天内采购的关键词/数字模式（确定性解析；不完美但可解释、可配置）
_TIMELINE_KEYWORDS = (
    "asap",
    "immediately",
    "right away",
    "this week",
    "next week",
    "this month",
    "本周",
    "这周",
    "下周",
    "尽快",
    "立刻",
    "马上",
    "两周",
    "半个月",
    "月内",
    "本月",
    "一个月内",
)
_DAYS_RE = re.compile(r"(\d+)\s*(?:天|days?\b)", re.IGNORECASE)
_WEEKS_RE = re.compile(r"(\d+)\s*(?:周|weeks?\b)", re.IGNORECASE)


def is_business_email(email: str | None) -> bool:
    if not email or "@" not in email:
        return False
    domain = email.rsplit("@", 1)[1].strip().lower()
    return bool(domain) and domain not in FREE_EMAIL_DOMAINS


def timeline_within_30d(text: str | None) -> bool:
    if not text:
        return False
    lowered = text.lower()
    if any(kw in lowered for kw in _TIMELINE_KEYWORDS):
        return True
    days = _DAYS_RE.search(lowered)
    if days and int(days.group(1)) <= 30:
        return True
    weeks = _WEEKS_RE.search(lowered)
    if weeks and int(weeks.group(1)) <= 4:
        return True
    return False


def team_size_fits(text: str | None) -> bool:
    if not text:
        return False
    match = re.search(r"\d+", text)
    return match is not None and int(match.group()) >= TEAM_SIZE_FIT_MIN


# (规则名, 分值, 命中判断)——§8 的表，规则名即 score_reasons 内容
RULES: list[tuple[str, int, Callable[[dict[str, Any]], bool]]] = [
    ("company_email", 15, lambda d: is_business_email(d.get("business_email"))),
    ("clear_need", 20, lambda d: bool((d.get("requirement") or "").strip())),
    ("team_size_fit", 15, lambda d: team_size_fits(d.get("team_size"))),
    ("budget_given", 15, lambda d: bool((d.get("budget_range") or "").strip())),
    ("timeline_30d", 20, lambda d: timeline_within_30d(d.get("purchase_timeline"))),
    ("asked_demo", 25, lambda d: bool(d.get("asked_demo"))),
    ("freebie_only", -20, lambda d: bool(d.get("freebie_only"))),
]


@dataclass(frozen=True)
class ScoreResult:
    score: int
    grade: str  # low|medium|high
    reasons: list[str]


def grade_of(score: int) -> str:
    if score <= GRADE_LOW_MAX:
        return "low"
    if score <= GRADE_MEDIUM_MAX:
        return "medium"
    return "high"


def score_lead(lead: dict[str, Any]) -> ScoreResult:
    """入参为 lead 字段字典（含 asked_demo/freebie_only 事实列）。"""
    score = 0
    reasons: list[str] = []
    for name, points, predicate in RULES:
        if predicate(lead):
            score += points
            reasons.append(name)
    return ScoreResult(score=score, grade=grade_of(score), reasons=reasons)
