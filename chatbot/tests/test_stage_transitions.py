"""Stage machine: legacy migration, forward-only progression, HANDOFF absorbing."""

import pytest

from app.graph.sales_stage import (
    LEGACY_STAGE_MAP,
    ORDER,
    SalesStage,
    derive_stage,
    normalize_stage,
)


# ── migration of v1 checkpoints ──────────────────────────────
@pytest.mark.parametrize("legacy,expected", LEGACY_STAGE_MAP.items())
def test_legacy_values_migrate(legacy, expected):
    assert normalize_stage(legacy) == expected


def test_canonical_values_pass_through():
    for stage in ORDER + (SalesStage.HANDOFF,):
        assert normalize_stage(stage) == stage


@pytest.mark.parametrize("value", [None, "", "   ", "rác", 0])
def test_unknown_values_degrade_to_moi(value):
    assert normalize_stage(value) == SalesStage.MOI


def test_old_checkpoint_loads_without_crashing():
    old_state = {"sales_stage": "đang tư vấn", "lead_profile": {"lop": "7"}}
    assert derive_stage(old_state["lead_profile"], old_state["sales_stage"]) \
        == SalesStage.DA_RO_NHU_CAU


# ── derive_stage ─────────────────────────────────────────────
def test_empty_profile_stays_moi():
    assert derive_stage({}, None) == SalesStage.MOI


def test_lop_alone_is_not_enough():
    assert derive_stage({"lop": "7"}, SalesStage.MOI) == SalesStage.MOI


def test_lop_plus_tinh_trang_advances():
    profile = {"lop": "7", "tinh_trang": "mất gốc"}
    assert derive_stage(profile, SalesStage.MOI) == SalesStage.DA_RO_NHU_CAU


def test_phone_advances_to_co_sdt():
    assert derive_stage({"sdt": "0912345678"}, SalesStage.MOI) == SalesStage.CO_SDT


def test_never_goes_backwards():
    # A quoted price put us at DA_BAO_GIA; an empty profile must not undo it.
    assert derive_stage({}, SalesStage.DA_BAO_GIA) == SalesStage.DA_BAO_GIA
    assert derive_stage({"lop": "7", "tinh_trang": "yếu"}, SalesStage.DA_HEN_LICH) \
        == SalesStage.DA_HEN_LICH


def test_handoff_is_absorbing():
    assert derive_stage({"sdt": "0912345678"}, SalesStage.HANDOFF) == SalesStage.HANDOFF
    assert derive_stage({}, "cần người") == SalesStage.HANDOFF


def test_phone_wins_over_lower_derived_signal():
    profile = {"lop": "7", "tinh_trang": "yếu", "sdt": "0912345678"}
    assert derive_stage(profile, SalesStage.MOI) == SalesStage.CO_SDT
