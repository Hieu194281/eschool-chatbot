#!/usr/bin/env python3
"""Turn a shadow-mode metrics log into the go/no-go table.

Usage:
    python scripts/summarize-shadow-metrics.py <logfile> [--min-turns N]
    cat app.log | python scripts/summarize-shadow-metrics.py -

Reads JSON lines emitted by `app.common.metrics_logger`; any other line is
ignored, so a plain application log can be piped straight in.

Exit codes: 0 = all gates pass · 1 = a gate failed · 2 = not enough volume to
judge. The volume check comes first on purpose — a clean table computed from 12
turns is not evidence, and reading it as if it were is how a bad rollout gets
approved (red-team #16).
"""

from __future__ import annotations

import json
import sys
from collections import Counter

DEFAULT_MIN_TURNS = 200

# (label, predicate on the computed stats, human-readable threshold)
GATES = (
    ("Tỉ lệ draft bị guard chặn", lambda s: s["block_rate"] < 0.10, "<10%"),
    ("Không dồn vào 1 loại vi phạm",
     lambda s: s["top_violation_share"] < 0.70 or s["blocked"] == 0,
     "loại nhiều nhất <70% số ca chặn"),
    # A RATE, not a count: as an absolute it fails the first time the mitigation
    # works, so over a long run it could never pass and would be ignored.
    ("Tỉ lệ lượt bot nài SĐT lần 2", lambda s: s["nag_rate"] < 0.01, "<1% số lượt"),
    ("Latency p95", lambda s: s["p95_latency_ms"] < 15_000, "<15s"),
)


def read_events(stream):
    for line in stream:
        start = line.find("{")
        if start < 0:
            continue
        try:
            event = json.loads(line[start:])
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict) and "event" in event:
            yield event


def _percentile(values: list[int], pct: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round((len(ordered) - 1) * pct)))
    return ordered[index]


def summarize(events: list[dict]) -> dict:
    guard = [e for e in events if e["event"] == "guard"]
    blocked = [e for e in guard if e.get("guard_blocked")]
    violations = Counter(k for e in blocked for k in e.get("violation_kinds", []))
    latencies = [e["latency_ms"] for e in events
                 if e["event"] == "turn" and isinstance(e.get("latency_ms"), int)]
    turns = len([e for e in events if e["event"] == "turn"])
    suppressed = sum(1 for e in events if e.get("phone_suppressed"))

    return {
        "turns": turns,
        "guard_checks": len(guard),
        "blocked": len(blocked),
        "block_rate": len(blocked) / len(guard) if guard else 0.0,
        "violations": violations,
        "top_violation_share": (violations.most_common(1)[0][1] / len(blocked)
                                if blocked else 0.0),
        "objections": Counter(e.get("objection_type") for e in events
                              if e["event"] == "objection"),
        "escalated": sum(1 for e in events if e.get("escalated")),
        "stages": Counter(e.get("stage") for e in events if e["event"] == "lead"),
        "leads_with_phone": sum(1 for e in events
                                if e["event"] == "lead" and e.get("has_phone")),
        "phone_asked": sum(1 for e in events if e.get("phone_asked")),
        "phone_suppressed": suppressed,
        "nag_rate": suppressed / turns if turns else 0.0,
        "p95_latency_ms": _percentile(latencies, 0.95),
    }


def _print_report(stats: dict) -> None:
    print(f"\nLượt hội thoại: {stats['turns']}   guard chạy: {stats['guard_checks']}")
    print(f"Guard chặn:     {stats['blocked']} ({stats['block_rate']:.1%})")
    for kind, count in stats["violations"].most_common():
        print(f"  - {kind:<12} {count}")

    print(f"\nObjection: {dict(stats['objections'])}   escalate: {stats['escalated']}")
    print(f"Drop-off theo stage: {dict(stats['stages'])}")
    print(f"Lead có SĐT: {stats['leads_with_phone']}")
    print(f"Xin SĐT: {stats['phone_asked']}   bị chặn nài lần 2: "
          f"{stats['phone_suppressed']} ({stats['nag_rate']:.2%})")
    print(f"Latency p95: {stats['p95_latency_ms']}ms")


def _parse_args(argv: list[str]) -> tuple[str, int]:
    """Positional path + `--min-turns N`.

    The option's VALUE has to be consumed too — filtering only tokens that start
    with `--` left the number behind, and it became the log path.
    """
    path, min_turns, rest = "-", DEFAULT_MIN_TURNS, list(argv[1:])
    while rest:
        token = rest.pop(0)
        if token == "--min-turns" and rest:
            min_turns = int(rest.pop(0))
        elif not token.startswith("--"):
            path = token
    return path, min_turns


def main(argv: list[str]) -> int:
    path, min_turns = _parse_args(argv)
    if path == "-":
        events = list(read_events(sys.stdin))
    else:
        with open(path, encoding="utf-8") as handle:
            events = list(read_events(handle))

    if not events:
        print("Không đọc được event nào — sai file log?")
        return 2

    stats = summarize(events)
    _print_report(stats)

    if stats["turns"] < min_turns:
        print(f"\n=> CHƯA đủ volume ({stats['turns']}/{min_turns} lượt). "
              f"Số liệu chưa đủ để kết luận — chạy shadow thêm.")
        return 2

    print("\nCổng go-live:")
    failed = 0
    for label, check, threshold in GATES:
        ok = check(stats)
        failed += not ok
        print(f"  [{'PASS' if ok else 'FAIL'}] {label} ({threshold})")

    print("\n=> " + ("Đạt cổng — có thể tắt SHADOW_MODE." if not failed
                     else f"{failed} cổng chưa đạt — CHƯA thả tự động."))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
