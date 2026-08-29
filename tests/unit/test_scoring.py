"""§8 评分规则全矩阵（纯函数，无外部依赖）。"""

from domain.scoring import (
    grade_of,
    is_business_email,
    score_lead,
    team_size_fits,
    timeline_within_30d,
)


def test_empty_lead_scores_zero_low() -> None:
    result = score_lead({})
    assert result.score == 0 and result.grade == "low" and result.reasons == []


def test_full_high_intent_lead() -> None:
    """演示剧本口径：公司邮箱+明确需求+50人团队+预算+下周采购+要 Demo → high。"""
    result = score_lead(
        {
            "business_email": "cto@acme-corp.com",
            "requirement": "需要接入客服机器人",
            "team_size": "50 人",
            "budget_range": "1-2 万美元",
            "purchase_timeline": "下周就要上线",
            "asked_demo": True,
        }
    )
    assert result.score == 15 + 20 + 15 + 15 + 20 + 25 == 110
    assert result.grade == "high"
    assert result.reasons == [
        "company_email",
        "clear_need",
        "team_size_fit",
        "budget_given",
        "timeline_30d",
        "asked_demo",
    ]


def test_freebie_penalty() -> None:
    result = score_lead({"freebie_only": True})
    assert result.score == -20 and result.grade == "low"
    assert result.reasons == ["freebie_only"]


def test_grade_boundaries() -> None:
    assert grade_of(0) == "low"
    assert grade_of(29) == "low"
    assert grade_of(30) == "medium"
    assert grade_of(59) == "medium"
    assert grade_of(60) == "high"


def test_business_email_detection() -> None:
    assert is_business_email("a@corp.io")
    assert not is_business_email("a@gmail.com")
    assert not is_business_email("a@QQ.com")  # 大小写不敏感
    assert not is_business_email("not-an-email")
    assert not is_business_email(None)


def test_timeline_within_30d() -> None:
    for positive in (
        "下周",
        "本周内",
        "尽快",
        "两周内",
        "next week",
        "ASAP",
        "3 天内",
        "within 10 days",
        "4 周",
    ):
        assert timeline_within_30d(positive), positive
    for negative in ("45 天后", "6 weeks", "Q4 评估", "明年", None, "还没定"):
        assert not timeline_within_30d(negative), negative


def test_team_size_fits() -> None:
    assert team_size_fits("50 人")
    assert team_size_fits("about 20 people")
    assert not team_size_fits("3")
    assert not team_size_fits("小团队")
    assert not team_size_fits(None)


def test_validate_production_settings() -> None:
    """第三轮评审：生产（https）弱配置必须拒绝启动；开发环境不拦。"""
    import pytest
    from domain.config import Settings, validate_production_settings

    # 开发环境（无 https）不校验
    validate_production_settings(Settings(public_base_url=""))

    weak = Settings(public_base_url="https://demo.example.com", jwt_secret="short")
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        validate_production_settings(weak)

    strong = Settings(
        public_base_url="https://demo.example.com",
        jwt_secret="x" * 40,
        admin_username="admin",
        admin_password_hash="$2b$12$abcdefghijklmnopqrstuv",
        settings_encryption_key="k" * 44,
        telegram_webhook_secret="s" * 40,
    )
    validate_production_settings(strong)  # 不抛
