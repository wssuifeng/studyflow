"""Structured teaching-chain listing for the authoring-quality report (W1 §4).

TEACHING_CHAIN_LIST is a list output, not a judgment: per lesson it reports the
MAIN-track progression chains of the analyzed package with their stage sequence
and per-item stage. The MAIN/SUPPLEMENT track distinction happens at import
time; the quality tool analyzes one explicit package, so every progression
chain in that package is mainline material for this listing.
"""
from __future__ import annotations


def build_teaching_chain_list(package):
    result = []
    for lesson in package.get("lessons", []):
        chains = {}
        without_chain = []
        for exercise in lesson.get("exercises", []):
            english = exercise.get("english")
            if not english:
                continue
            progression = english.get("progression") or {}
            chain_id = progression.get("chain_id")
            if not chain_id:
                without_chain.append(exercise.get("id"))
                continue
            chain = chains.setdefault(chain_id, {"chain_id": chain_id, "stage_sequence": [], "items": []})
            chain["stage_sequence"].append(progression.get("stage"))
            chain["items"].append({"exercise_id": exercise.get("id"), "stage": progression.get("stage")})
        result.append({
            "lesson_id": lesson.get("id"),
            "chains": list(chains.values()),
            "english_exercises_without_chain": without_chain,
        })
    return result
