"""Shared story-case (content/story-case) schema-fit primitives.

PLACEHOLDER_PATTERNS was copy-pasted byte-for-byte across render-deck.py
(the renderer's --skip-fit-check refusal) and validate-deck.py (the deck.json
business-rule check); the min-length thresholds were expressed two ways. They
drive the SAME fit decision, so a divergence between the copies would let a
beat that one tool rejects slip past the other. Single-sourced here per F-15;
both modules import from this file.

NOTE: validate-deck.py's check_business_rules() inlines the per-field minimums
(1 / 2 / 10) in its fit_fields table — those MUST stay equal to _min_len_for()
below. _min_len_for is the canonical mapping. stdlib-only, no deps.
"""


def get_path(d, dotted: str):
    """Walk a dotted path through nested dicts; KeyError if any hop is missing."""
    cur = d
    for k in dotted.split("."):
        if not isinstance(cur, dict) or k not in cur:
            raise KeyError(dotted)
        cur = cur[k]
    return cur


# Strings that look like unfilled placeholders — a story-case beat carrying one
# of these doesn't fit the schema (author should take Path B).
PLACEHOLDER_PATTERNS = (
    r"\b(TBD|TBC|TODO|XXX|N/?A|FIXME)\b",
    r"(待补|具体待补|占位|稍后补充|有待补充|待定|暂无|未填|None)",
    r"^[\s\.\-…—_]+$",
    r"^(\?+|？+)$",
    r"\.{3,}|…{2,}",
)

_MIN_LEN_FULL = 10        # arc.pain / arc.conflict / arc.solution
_MIN_LEN_ACCENT = 2       # *.accent — highlight words
_MIN_LEN_CONNECTIVE = 1   # *.lead / *.tail — connective tissue

STORY_CASE_FIT_CHECK = (
    "hook.lead", "hook.accent", "hook.tail",
    "arc.pain", "arc.conflict", "arc.solution",
    "arc.value.lead", "arc.value.accent", "arc.value.tail",
)


def _min_len_for(path: str) -> int:
    if path.endswith(".accent"):
        return _MIN_LEN_ACCENT
    if path.endswith((".lead", ".tail")):
        return _MIN_LEN_CONNECTIVE
    return _MIN_LEN_FULL
