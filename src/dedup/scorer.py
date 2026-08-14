from dataclasses import dataclass
from enum import Enum

from rapidfuzz import fuzz

from config.constants import (
    CG_JACCARD_THRESHOLD,
    NAME_SIM_THRESHOLD,
    OBJECT_OVERLAP_THRESHOLD,
    NAME_GRAY_THRESHOLD,
    DESC_COSINE_THRESHOLD,
    OBJECT_GRAY_THRESHOLD,
    DESC_COSINE_SECONDARY,
    OVERLAP_GRAY_THRESHOLD,
    NAME_CORROB_THRESHOLD,
)


class Tier(Enum):
    AUTO_MERGE = "auto_merge"
    GRAY_ZONE = "gray_zone"
    NO_MERGE = "no_merge"


@dataclass(frozen=True)
class ScoreBreakdown:
    cg_jaccard: float
    overlap_coeff: float
    name_sim: float
    object_jaccard: float
    cg_set_equality: bool
    # Business-description cosine similarity (0.0 when the caller does not supply
    # an embedding signal, e.g. tests or pure-structural scoring).
    desc_cosine: float = 0.0


def _jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 0.0
    return len(a & b) / len(a | b)


def _overlap_coeff(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def score_pair(proposed: dict, candidate: dict, desc_cosine: float = 0.0) -> ScoreBreakdown:
    pcg = set(proposed.get("component_groups", []))
    ccg = set(candidate.get("component_groups", []))
    po = set(proposed.get("primary_objects", []))
    co = set(candidate.get("primary_objects", []))
    return ScoreBreakdown(
        cg_jaccard=_jaccard(pcg, ccg),
        overlap_coeff=_overlap_coeff(pcg, ccg),
        name_sim=fuzz.token_set_ratio(
            proposed.get("name", ""), candidate.get("name", "")
        ),
        object_jaccard=_jaccard(po, co),
        cg_set_equality=(pcg == ccg and len(pcg) >= 2),
        desc_cosine=desc_cosine,
    )


def tier(score: ScoreBreakdown) -> Tier:
    # AUTO_MERGE stays conservative: only confident STRUCTURAL equivalence merges
    # without an LLM look. Identical CG sets, or high CG overlap corroborated by
    # name/object similarity.
    if score.cg_set_equality:
        return Tier.AUTO_MERGE
    if score.cg_jaccard >= CG_JACCARD_THRESHOLD and (
        score.name_sim >= NAME_SIM_THRESHOLD or score.object_jaccard >= OBJECT_OVERLAP_THRESHOLD
    ):
        return Tier.AUTO_MERGE
    # GRAY_ZONE defers to the LLM adjudicator (which reads full descriptions).
    # Any ONE strong signal is enough to defer — CG Jaccard is no longer a
    # necessary gate, so same-named / semantically-identical functions built
    # from different component-group sets are caught instead of silently
    # inserted as duplicates.
    if score.cg_jaccard >= CG_JACCARD_THRESHOLD:
        return Tier.GRAY_ZONE
    if score.name_sim >= NAME_GRAY_THRESHOLD:
        return Tier.GRAY_ZONE
    if score.desc_cosine >= DESC_COSINE_THRESHOLD:
        return Tier.GRAY_ZONE
    # Containment: the smaller function's component groups are (near-)subset of
    # the larger's. Caught by overlap_coeff (not the size-sensitive cg_jaccard),
    # but only deferred WITH a corroborating name or description signal so a
    # granular function sharing one common CG with a big aggregate is not
    # deferred on containment alone.
    if score.overlap_coeff >= OVERLAP_GRAY_THRESHOLD and (
        score.name_sim >= NAME_CORROB_THRESHOLD or score.desc_cosine >= DESC_COSINE_SECONDARY
    ):
        return Tier.GRAY_ZONE
    # Granular cross-domain recurrence: same primary object(s) AND a moderately
    # similar description. The secondary cosine gate keeps genuinely distinct
    # functions that merely share a common object out of the gray zone.
    if score.object_jaccard >= OBJECT_GRAY_THRESHOLD and score.desc_cosine >= DESC_COSINE_SECONDARY:
        return Tier.GRAY_ZONE
    return Tier.NO_MERGE
