"""§7 合并规则：覆盖/保留/拒绝/邮箱校验/事实布尔（纯函数）。"""

from domain.lead_merge import merge_lead, missing_key_fields
from domain.schemas import LeadExtraction


def test_new_values_override_with_audit() -> None:
    result = merge_lead(
        {"company": "旧公司", "requirement": None},
        LeadExtraction(company="新公司", requirement="要机器人"),
    )
    assert result.updates == {"company": "新公司", "requirement": "要机器人"}
    assert {"field": "company", "old": "旧公司", "new": "新公司"} in result.audit
    assert result.changed


def test_empty_never_clobbers() -> None:
    result = merge_lead({"company": "Acme"}, LeadExtraction(company=None, name="  "))
    assert result.updates == {} and not result.changed


def test_same_value_no_update() -> None:
    result = merge_lead({"company": "Acme"}, LeadExtraction(company="Acme"))
    assert result.updates == {}


def test_invalid_email_dropped() -> None:
    result = merge_lead({}, LeadExtraction(business_email="不是邮箱"))
    assert "business_email" not in result.updates
    result = merge_lead({}, LeadExtraction(business_email="a@corp.io"))
    assert result.updates["business_email"] == "a@corp.io"


def test_refused_fields_merge() -> None:
    result = merge_lead(
        {"declined_fields": ["budget_range"]},
        LeadExtraction(refused_fields=["budget_range", "team_size"]),
    )
    assert result.declined_added == ["team_size"]
    assert result.changed


def test_integrations_union() -> None:
    result = merge_lead(
        {"integrations": ["hubspot"]}, LeadExtraction(integrations=["hubspot", "slack"])
    )
    assert result.updates["integrations"] == ["hubspot", "slack"]


def test_asked_demo_sticky_freebie_follows() -> None:
    # asked_demo 只升不降
    result = merge_lead({"asked_demo": True}, LeadExtraction(asked_demo_or_quote=False))
    assert "asked_demo" not in result.updates
    # freebie_only 跟随最新判断
    result = merge_lead({"freebie_only": True}, LeadExtraction(freebie_only=False))
    assert result.updates["freebie_only"] is False


def test_missing_key_fields_excludes_filled_and_declined() -> None:
    merged = {"business_email": "a@corp.io", "company": "Acme"}
    missing = missing_key_fields(merged, declined=["budget_range"])
    assert "business_email" not in missing and "company" not in missing
    assert "budget_range" not in missing
    assert "requirement" in missing and "team_size" in missing
