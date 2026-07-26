"""Canonical `sales_stage` values — ONE source of truth for the whole graph.

Before this module the four write-sites (`pricing_guard`, and three in
`lead_tools`) each spelled the stage as a Vietnamese literal. Any typo or missed
site produces a state that no reader recognises and NOTHING fails loudly — the
sales machine just silently stops advancing. Constants make a miss a NameError.

Order matters: `ORDER` is what "chỉ tiến, không lùi" is measured against in
Phase 04's `derive_stage`. `HANDOFF` is deliberately outside that ladder — it is
an exit, reachable from anywhere.
"""

from __future__ import annotations


class SalesStage:
    MOI = "moi"                       # mới vào, chưa biết gì về khách
    DA_RO_NHU_CAU = "da_ro_nhu_cau"   # biết lớp + tình trạng
    DA_BAO_GIA = "da_bao_gia"         # đã nói học phí
    CO_SDT = "co_sdt"                 # đã có số điện thoại
    DA_HEN_LICH = "da_hen_lich"       # đã chốt lịch học thử → NGỪNG bán
    HANDOFF = "handoff"               # người thật tiếp quản → bot im


# Progression ladder (HANDOFF excluded — it is an exit, not a rung).
ORDER = (
    SalesStage.MOI,
    SalesStage.DA_RO_NHU_CAU,
    SalesStage.DA_BAO_GIA,
    SalesStage.CO_SDT,
    SalesStage.DA_HEN_LICH,
)

ALL_STAGES = ORDER + (SalesStage.HANDOFF,)

# v1 wrote descriptive Vietnamese strings. Live checkpoints still hold them, so a
# READ must translate; nothing may ever write them again.
LEGACY_STAGE_MAP = {
    "mới": SalesStage.MOI,
    "đang tư vấn": SalesStage.DA_RO_NHU_CAU,
    "đã xin SĐT": SalesStage.CO_SDT,
    "đã chốt": SalesStage.DA_HEN_LICH,
    "cần người": SalesStage.HANDOFF,
}


def normalize_stage(value) -> str:
    """Any stored value → a canonical stage. Unknown/empty → MOI (never crash)."""
    text = (value or "").strip()
    if text in ALL_STAGES:
        return text
    return LEGACY_STAGE_MAP.get(text, SalesStage.MOI)


def advance_stage(current, target: str) -> str:
    """Move to `target` only if it is further along. HANDOFF stays put."""
    current = normalize_stage(current)
    if current == SalesStage.HANDOFF or target == SalesStage.HANDOFF:
        return SalesStage.HANDOFF if target == SalesStage.HANDOFF else current
    return max(current, target, key=ORDER.index)


def derive_stage(profile: dict, current) -> str:
    """Stage implied by what we know, never lower than where we already are.

    Going backwards would restart the elicitation the customer already answered,
    which reads as the bot forgetting them. HANDOFF is absorbing: once a human is
    involved, no profile field pulls the bot back into selling.

    `DA_BAO_GIA` and `DA_HEN_LICH` are NOT derivable from the profile — they are
    events (a price was quoted, a trial was booked) and are set at their site.
    """
    current = normalize_stage(current)
    if current == SalesStage.HANDOFF:
        return SalesStage.HANDOFF

    profile = profile or {}
    implied = SalesStage.MOI
    if profile.get("lop") and profile.get("tinh_trang"):
        implied = SalesStage.DA_RO_NHU_CAU
    if profile.get("sdt"):
        implied = SalesStage.CO_SDT

    return max(current, implied, key=ORDER.index)
