"""Metrics log is a NEW PII surface — the whitelist is what keeps it clean."""

import json
import logging

from app.common.metrics_logger import ALLOWED_FIELDS, emit
from app.graph.nodes.guard_checks import Kind, Violation, kinds_of


def _emitted(caplog):
    return [json.loads(r.message) for r in caplog.records if r.name == "shadow.metrics"]


def test_allowed_fields_pass_through(caplog):
    with caplog.at_level(logging.INFO, logger="shadow.metrics"):
        emit(event="guard", guard_blocked=True, violation_kinds=[Kind.MONEY])
    assert _emitted(caplog) == [
        {"event": "guard", "guard_blocked": True, "violation_kinds": ["money"]}
    ]


def test_unknown_fields_are_dropped(caplog):
    with caplog.at_level(logging.INFO, logger="shadow.metrics"):
        emit(event="lead", sdt="0912345678", draft="Dạ học phí 5 triệu",
             khung_gio_tien="tối sau 19h", user_id="psid-123")
    (line,) = _emitted(caplog)
    assert line == {"event": "lead"}


def test_no_pii_reaches_the_log(caplog):
    with caplog.at_level(logging.INFO, logger="shadow.metrics"):
        emit(event="lead", stage="co_sdt", has_phone=True, sdt="0912345678")
    text = "".join(r.message for r in caplog.records)
    assert "0912345678" not in text
    assert '"has_phone": true' in text


def test_non_scalar_values_are_dropped(caplog):
    with caplog.at_level(logging.INFO, logger="shadow.metrics"):
        emit(event="guard", stage={"nested": "object"})
    assert _emitted(caplog) == [{"event": "guard"}]


def test_emitting_nothing_writes_nothing(caplog):
    with caplog.at_level(logging.INFO, logger="shadow.metrics"):
        emit(unknown_only="x")
    assert _emitted(caplog) == []


def test_whitelist_covers_what_the_summarizer_reads():
    needed = {"event", "guard_blocked", "violation_kinds", "objection_type", "escalated",
              "stage", "has_phone", "phone_asked", "phone_suppressed", "latency_ms"}
    assert needed <= ALLOWED_FIELDS


# ── violation kinds: enum in metrics, message in logs ────────
def test_violation_behaves_as_a_string_and_carries_a_kind():
    violation = Violation(Kind.MONEY, "số tiền không thuộc KB: '4tr5'")
    assert isinstance(violation, str)
    assert "4tr5" in violation and violation.kind == "money"


def test_kinds_of_dedupes_and_sorts():
    violations = [Violation(Kind.MONEY, "a"), Violation(Kind.MONEY, "b"),
                  Violation(Kind.SCHEDULE, "c")]
    assert kinds_of(violations) == ["money", "schedule"]


def test_kinds_of_tolerates_a_plain_string():
    assert kinds_of(["chuỗi thường"]) == ["internal"]


def test_guard_emits_kinds_not_messages(caplog):
    from app.graph.nodes.pricing_guard import evaluate_draft

    course = {"course_id": "C1", "ten_khoa": "IELTS Cấp Tốc", "tu_khoa": [],
              "facts": "Học phí: 5.000.000"}
    verdict = evaluate_draft("Khóa IELTS Cấp Tốc học phí 9.000.000đ ạ", [course])
    with caplog.at_level(logging.INFO, logger="shadow.metrics"):
        emit(event="guard", guard_blocked=True, violation_kinds=kinds_of(verdict.violations))
    (line,) = _emitted(caplog)
    assert line["violation_kinds"] == ["money"]
    assert "9.000.000" not in json.dumps(line)      # the draft never leaks
