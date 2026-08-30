"""线索评分：纯函数、表驱动规则（技术方案 §8）。

LLM 只负责提取事实，评分完全确定性、可解释（§9.1）；命中的规则名存入 score_reasons。
分值/阈值/团队规模下限/免费邮箱域可按客户实例配置（env `SCORING_OVERRIDES`，JSON），
这是 §20 产品化定制路线的"20% 配置"之一——改配置不改代码。
"""

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

# 免费邮箱域（§8）：客户可经 extra_free_domains 追加
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

DEFAULT_POINTS: dict[str, int] = {
    "company_email": 15,
    "clear_need": 20,
    "team_size_fit": 15,
    "budget_given": 15,
    "timeline_30d": 20,
    "asked_demo": 25,
    "freebie_only": -20,
}

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


@dataclass(frozen=True)
class ScoringConfig:
    """按客户实例可覆盖的评分参数（SCORING_OVERRIDES，见 config_from_json）。"""

    points: Mapping[str, int] = field(default_factory=lambda: dict(DEFAULT_POINTS))
    team_size_min: int = 10
    medium_min: int = 30
    high_min: int = 60
    extra_free_domains: frozenset[str] = frozenset()


@lru_cache(maxsize=8)
def config_from_json(raw: str) -> ScoringConfig:
    """解析 env 覆盖，如：
    {"points": {"asked_demo": 30}, "team_size_min": 5, "high_min": 55,
     "extra_free_domains": ["example.com"]}
    未提供的键用默认值；解析失败抛错（宁可启动失败，不可静默用错规则）。
    """
    if not raw.strip():
        return ScoringConfig()
    data = json.loads(raw)
    return ScoringConfig(
        points={**DEFAULT_POINTS, **{k: int(v) for k, v in data.get("points", {}).items()}},
        team_size_min=int(data.get("team_size_min", 10)),
        medium_min=int(data.get("medium_min", 30)),
        high_min=int(data.get("high_min", 60)),
        extra_free_domains=frozenset(str(d).lower() for d in data.get("extra_free_domains", [])),
    )


def get_config() -> ScoringConfig:
    from domain.config import get_settings

    return config_from_json(get_settings().scoring_overrides)


def is_business_email(email: str | None, extra_free_domains: frozenset[str] = frozenset()) -> bool:
    if not email or "@" not in email:
        return False
    domain = email.rsplit("@", 1)[1].strip().lower()
    return bool(domain) and domain not in FREE_EMAIL_DOMAINS and domain not in extra_free_domains


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


def team_size_fits(text: str | None, minimum: int = 10) -> bool:
    if not text:
        return False
    match = re.search(r"\d+", text)
    return match is not None and int(match.group()) >= minimum


@dataclass(frozen=True)
class ScoreResult:
    score: int
    grade: str  # low|medium|high
    reasons: list[str]


def grade_of(score: int, config: ScoringConfig | None = None) -> str:
    cfg = config or ScoringConfig()
    if score < cfg.medium_min:
        return "low"
    if score < cfg.high_min:
        return "medium"
    return "high"


def score_lead(lead: dict[str, Any], config: ScoringConfig | None = None) -> ScoreResult:
    """入参为 lead 字段字典（含 asked_demo/freebie_only 事实列）。"""
    cfg = config if config is not None else get_config()
    hits: list[tuple[str, bool]] = [
        ("company_email", is_business_email(lead.get("business_email"), cfg.extra_free_domains)),
        ("clear_need", bool((lead.get("requirement") or "").strip())),
        ("team_size_fit", team_size_fits(lead.get("team_size"), cfg.team_size_min)),
        ("budget_given", bool((lead.get("budget_range") or "").strip())),
        ("timeline_30d", timeline_within_30d(lead.get("purchase_timeline"))),
        ("asked_demo", bool(lead.get("asked_demo"))),
        ("freebie_only", bool(lead.get("freebie_only"))),
    ]
    score = sum(cfg.points.get(name, 0) for name, hit in hits if hit)
    reasons = [name for name, hit in hits if hit]
    return ScoreResult(score=score, grade=grade_of(score, cfg), reasons=reasons)
