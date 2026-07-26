"""Every `sales_stage` write must use the shared constants (plan review C4).

A missed write-site does not raise — it produces a stage string no reader
recognises and the sales machine silently stops advancing. This test is the alarm.
"""

import re
from pathlib import Path

import pytest

from app.graph.sales_stage import ALL_STAGES, ORDER, SalesStage

APP_DIR = Path(__file__).resolve().parents[1] / "app"

# The v1 values. Any of these still being written means a site was missed.
LEGACY_VALUES = ("mới", "đang tư vấn", "đã xin SĐT", "đã chốt", "cần người")

_WRITE_RE = re.compile(r"[\"']sales_stage[\"']\s*:\s*(?P<value>[^,}\n]+)")


def _write_sites():
    for path in APP_DIR.rglob("*.py"):
        for match in _WRITE_RE.finditer(path.read_text(encoding="utf-8")):
            yield path.relative_to(APP_DIR).as_posix(), match.group("value").strip()


def test_every_write_site_uses_the_constants():
    offenders = [
        (path, value) for path, value in _write_sites()
        if not (value.startswith("SalesStage.") or value.startswith("stage"))
    ]
    assert offenders == [], f"sales_stage written with a raw literal: {offenders}"


@pytest.mark.parametrize("legacy", LEGACY_VALUES)
def test_no_legacy_stage_literal_remains(legacy):
    # `sales_stage.py` is the ONE allowed home for them — LEGACY_STAGE_MAP has to
    # spell them out to migrate checkpoints written by v1.
    hits = [p.name for p in APP_DIR.rglob("*.py")
            if p.name != "sales_stage.py" and f'"{legacy}"' in p.read_text(encoding="utf-8")]
    assert hits == []


def test_legacy_map_covers_every_v1_value():
    from app.graph.sales_stage import LEGACY_STAGE_MAP

    assert set(LEGACY_VALUES) == set(LEGACY_STAGE_MAP)


def test_write_sites_are_actually_found():
    # Guards the regex itself — a test that silently matches nothing proves nothing.
    assert len(list(_write_sites())) >= 5


def test_handoff_is_outside_the_progression_ladder():
    assert SalesStage.HANDOFF not in ORDER
    assert set(ALL_STAGES) == set(ORDER) | {SalesStage.HANDOFF}
