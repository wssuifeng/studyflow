"""Deterministic rule registry for authoring quality (single Core implementation).

Migrated rules keep the rule names, paths, evidence shapes and thresholds of
``skills/studyflow-agent/scripts/authoring_quality.py`` verbatim (design
``docs/30_系统设计/W1生成侧质量工具与接口详细设计-v1.md`` §4/§7: identical input must
yield identical rule/path/evidence). Rules added by that design §4 are
deterministic triggers only; every semantic conclusion stays with human review.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter

RULE_VERSION = "authoring-quality/4"

# Main design 生成侧质量闭环与主题统一设计-v1.md §4.2 conclusion classes.
FIVE_CLASSES = ("deterministic_error", "content_defect", "review_required", "presentation_defect", "advisory")

# W1 §4 classification table. Migrated rules absent from that table follow the
# §4.2 split: automatic candidates awaiting adjudication are review_required,
# optional-compression notes are advisory.
CLASSIFICATIONS = {
    "LONG_SECTION_REVIEW": "advisory",
    "REPEATED_BLOCK_TITLE": "review_required",
    "REFERENCE_MISSING": "review_required",
    "REFERENCE_PLACEHOLDER": "review_required",
    "POSSIBLE_ANSWER_LEAK": "review_required",
    "EXAMPLE_REHEARSAL_CANDIDATE": "review_required",
    "ROLE_POS_CONFLICT_REVIEW": "review_required",
    "FRAGMENT_INDEPENDENCE_REVIEW": "review_required",
    "FRAGMENT_ROLE_CONTEXT_REVIEW": "review_required",
    "WORD_GLOSS_SENSE_REVIEW": "review_required",
    "AUTHOR_PHONETIC_REVIEW": "review_required",
    "DUPLICATE_VARIANT": "deterministic_error",
    "BLUEPRINT_REFERENCE_MISSING": "deterministic_error",
    "UNMAPPED_EXERCISE": "review_required",
    "MISSING_MAIN_SECTION": "review_required",
    "VARIANT_STRUCTURE_CANDIDATE": "review_required",
    "ENGLISH_PROMPT_LANGUAGE_REVIEW": "review_required",
    "NEAR_TEMPLATE_CANDIDATE": "review_required",
}

NEAR_TEMPLATE_SHARED_THRESHOLD = 0.6


def normalized(value):
    """Migrated verbatim from the Skill script."""
    return " ".join(unicodedata.normalize("NFKC", str(value)).casefold().split()).strip(".,!?;。！？")


def structural_key(value):
    """Punctuation/case-insensitive projection for VARIANT_STRUCTURE_CANDIDATE.

    Drops Unicode punctuation/symbol characters, casefolds and collapses
    whitespace, so a difference that survives ``normalized`` but vanishes here
    is a pure punctuation/case difference.
    """
    text = unicodedata.normalize("NFKC", str(value)).casefold()
    kept = "".join(ch for ch in text if unicodedata.category(ch)[:1] not in ("P", "S"))
    return " ".join(kept.split())


def casefolded_tokens(value):
    return unicodedata.normalize("NFKC", str(value)).casefold().split()


def near_template_matches(target, stage, related_items, threshold=NEAR_TEMPLATE_SHARED_THRESHOLD):
    """Deterministic near-template trigger against --related packages (§4).

    Same declared stage, same token count, and at least ``threshold`` of the
    current item's tokens shared (multiset intersection over the item's own
    token count). A candidate for same-template tracing, never a verdict.
    """
    current = casefolded_tokens(target)
    if not current:
        return []
    matches = []
    for related_target, related_stage in related_items:
        if related_stage != stage:
            continue
        related = casefolded_tokens(related_target)
        if len(related) != len(current):
            continue
        counts = Counter(current)
        other = Counter(related)
        shared = sum(min(count, other[token]) for token, count in counts.items())
        ratio = shared / len(current)
        if ratio >= threshold:
            matches.append({
                "related_target": str(related_target),
                "stage": stage,
                "shared_tokens": shared,
                "total_tokens": len(current),
                "ratio": ratio,
                "action": "Same stage and token count with high token overlap against a related package; review template reuse",
            })
    return matches


_CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
_LATIN = re.compile(r"[A-Za-z]")


def prompt_language_reason(prompt):
    """English-item prompt is empty or appears to be in the target's language."""
    text = str(prompt)
    if not text.strip():
        return "empty_prompt"
    if _LATIN.search(text) and not _CJK.search(text):
        return "same_language_as_target"
    return None


def has_main_section(rows):
    """True when any section in the tree (including children) has role=main."""
    for row in rows:
        if row.get("role") == "main":
            return True
        if has_main_section(row.get("children", [])):
            return True
    return False


def section_tree_roles(rows):
    roles = []
    seen = set()

    def visit(items):
        for row in items:
            role = row.get("role")
            if role not in seen:
                seen.add(role)
                roles.append(role)
            visit(row.get("children", []))

    visit(rows)
    return roles


def section_tree_count(rows):
    total = 0

    def visit(items):
        nonlocal total
        for row in items:
            total += 1
            visit(row.get("children", []))

    visit(rows)
    return total
