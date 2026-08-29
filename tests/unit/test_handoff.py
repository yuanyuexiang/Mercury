"""§9 状态机迁移表全矩阵（纯函数）。"""

import pytest
from domain.handoff import HandoffError, next_status

LEGAL = [
    ("ai_active", "request_human", "handoff_pending"),
    ("handoff_pending", "accept", "human_active"),
    ("handoff_pending", "resume_ai", "ai_active"),
    ("human_active", "resume_ai", "ai_active"),
    ("ai_active", "close", "closed"),
    ("handoff_pending", "close", "closed"),
    ("human_active", "close", "closed"),
]

ILLEGAL = [
    ("ai_active", "accept"),
    ("ai_active", "resume_ai"),
    ("handoff_pending", "request_human"),
    ("human_active", "request_human"),
    ("human_active", "accept"),
    ("closed", "request_human"),
    ("closed", "accept"),
    ("closed", "resume_ai"),
    ("closed", "close"),
]


@pytest.mark.parametrize(("current", "event", "expected"), LEGAL)
def test_legal_transitions(current: str, event: str, expected: str) -> None:
    assert next_status(current, event) == expected


@pytest.mark.parametrize(("current", "event"), ILLEGAL)
def test_illegal_transitions_raise(current: str, event: str) -> None:
    with pytest.raises(HandoffError):
        next_status(current, event)
