from dataclasses import dataclass
from enum import Enum

from rapidfuzz import fuzz


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


def _jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 0.0
    return len(a & b) / len(a | b)


def _overlap_coeff(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def score_pair(proposed: dict, candidate: dict) -> ScoreBreakdown:
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
    )


def tier(score: ScoreBreakdown) -> Tier:
    if score.cg_set_equality:
        return Tier.AUTO_MERGE
    if score.cg_jaccard >= 0.8 and (
        score.name_sim >= 80 or score.object_jaccard >= 0.75
    ):
        return Tier.AUTO_MERGE
    if score.cg_jaccard >= 0.8:
        return Tier.GRAY_ZONE
    return Tier.NO_MERGE
