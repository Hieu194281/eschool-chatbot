"""The summarizer drives the go/no-go call, so its arithmetic is tested too."""

import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "summarize-shadow-metrics.py"


@pytest.fixture(scope="module")
def summarizer():
    spec = importlib.util.spec_from_file_location("shadow_summary", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _log(events):
    return [json.dumps(e, ensure_ascii=False) for e in events]


def test_application_log_lines_are_ignored(summarizer):
    lines = ["2026-07-26 INFO app starting up",
             '2026-07-26 INFO shadow.metrics {"event": "turn", "latency_ms": 1200}',
             "not json at all {oops"]
    events = list(summarizer.read_events(lines))
    assert events == [{"event": "turn", "latency_ms": 1200}]


def test_block_rate_and_violation_mix(summarizer):
    events = ([{"event": "guard", "guard_blocked": False, "violation_kinds": []}] * 8
              + [{"event": "guard", "guard_blocked": True, "violation_kinds": ["money"]},
                 {"event": "guard", "guard_blocked": True, "violation_kinds": ["schedule"]}])
    stats = summarizer.summarize(events)
    assert stats["blocked"] == 2
    assert stats["block_rate"] == pytest.approx(0.2)
    assert stats["top_violation_share"] == pytest.approx(0.5)


def test_no_blocks_does_not_divide_by_zero(summarizer):
    stats = summarizer.summarize([{"event": "turn", "latency_ms": 100}])
    assert stats["block_rate"] == 0.0 and stats["top_violation_share"] == 0.0


def test_p95_latency(summarizer):
    events = [{"event": "turn", "latency_ms": ms} for ms in range(1, 101)]
    # 95 of the 100 samples are ≤ 95.
    assert summarizer.summarize(events)["p95_latency_ms"] == 95


def test_p95_of_a_single_sample(summarizer):
    assert summarizer.summarize([{"event": "turn", "latency_ms": 7}])["p95_latency_ms"] == 7


def test_repeat_phone_ask_is_counted(summarizer):
    events = [{"event": "phone_ask", "phone_asked": True, "phone_suppressed": False},
              {"event": "phone_ask", "phone_asked": False, "phone_suppressed": True}]
    stats = summarizer.summarize(events)
    assert stats["phone_asked"] == 1 and stats["phone_suppressed"] == 1


def test_low_volume_blocks_a_verdict(summarizer, tmp_path, capsys):
    path = tmp_path / "shadow.log"
    path.write_text("\n".join(_log([{"event": "turn", "latency_ms": 500}] * 5)),
                    encoding="utf-8")
    code = summarizer.main(["prog", str(path)])
    assert code == 2                                    # not a pass, not a fail
    assert "CHƯA đủ volume" in capsys.readouterr().out


def test_healthy_run_passes_every_gate(summarizer, tmp_path, capsys):
    events = [{"event": "turn", "latency_ms": 4000} for _ in range(50)]
    events += [{"event": "guard", "guard_blocked": False, "violation_kinds": []}] * 48
    events += [{"event": "guard", "guard_blocked": True, "violation_kinds": ["money"]},
               {"event": "guard", "guard_blocked": True, "violation_kinds": ["schedule"]}]
    path = tmp_path / "shadow.log"
    path.write_text("\n".join(_log(events)), encoding="utf-8")

    assert summarizer.main(["prog", str(path), "--min-turns", "50"]) == 0
    assert "Đạt cổng" in capsys.readouterr().out


def test_nagging_for_a_phone_number_fails_the_gate(summarizer, tmp_path, capsys):
    events = [{"event": "turn", "latency_ms": 4000} for _ in range(50)]
    events.append({"event": "phone_ask", "phone_asked": False, "phone_suppressed": True})
    path = tmp_path / "shadow.log"
    path.write_text("\n".join(_log(events)), encoding="utf-8")

    assert summarizer.main(["prog", str(path), "--min-turns", "50"]) == 1
    assert "CHƯA thả tự động" in capsys.readouterr().out
