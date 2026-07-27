"""Assemble the in-context course catalog + watch its growth.

Pure presentation logic, split out of `vector_store.py` (200-LOC ceiling) and
unit-testable without a snapshot.

Two blocks, fixed order, both sorted by `course_id`:
- `[MỤC LỤC KHÓA]` — one ~25-token line per course. It is the table of contents
  the model uses to pick the right course among many long detail blocks, and it
  stays always-on at EVERY catalog size.
- `[CHI TIẾT KHÓA]` — the full prose + verbatim facts block per course. This is
  the layer that leaves the prompt first when the catalog outgrows `full` mode.

Stable sort matters beyond tidiness: an unchanged sync must produce a
byte-identical prefix or Gemini context caching stops hitting.
"""

from __future__ import annotations

INDEX_HEADER = "[MỤC LỤC KHÓA]"
DETAIL_HEADER = "[CHI TIẾT KHÓA]"

# Above this many courses, `full` mode stops being the right trade-off — see plan
# §Đường tăng trưởng. Switching is one flag + `get_course_detail(cid)`, not a
# refactor, because index/blocks are already keyed by course_id.
CATALOG_INDEX_THRESHOLD = 30

_OVERSIZED_WARNING = (
    "Catalog có %d khóa (>%d): prompt đang phình. HÀNH ĐỘNG: chuyển sang "
    "CATALOG_MODE=index — giữ [MỤC LỤC KHÓA] always-on và thêm tool "
    "get_course_detail(course_id) đọc course_blocks. Không cần refactor."
)


def build_catalog_text(course_index: dict, course_blocks: dict) -> str:
    """Index block then detail block, same course_id order in both."""
    if not course_blocks:
        return ""
    cids = sorted(course_blocks)
    index = "\n".join(course_index[cid] for cid in cids if cid in course_index)
    details = "\n\n".join(course_blocks[cid] for cid in cids)
    return f"{INDEX_HEADER}\n{index}\n\n{DETAIL_HEADER}\n{details}"


def warn_if_oversized(logger, course_count: int) -> None:
    """Log the ACTION to take, not just the number — a bare count gets ignored."""
    if course_count > CATALOG_INDEX_THRESHOLD:
        logger.warning(_OVERSIZED_WARNING, course_count, CATALOG_INDEX_THRESHOLD)
