from typing import Dict, Any
from pydantic import BaseModel, Field
from langchain_google_genai import ChatGoogleGenerativeAI
from src.state.schema import DomainState
from src.vector_store import registry
from src.dedup.scorer import score_pair, tier, Tier
import json
from src.prompts.loader import get_system_prompt

class ValidatorOutput(BaseModel):
    is_valid: bool = Field(description="True if the proposed functions pass criteria 1 (No Orphans) and 2 (Business Intent & Granularity).")
    validation_feedback: str = Field(description="If is_valid is False, provide detailed feedback referencing the specific rubric violation. If True, write 'Approved.'")

llm = ChatGoogleGenerativeAI(model="gemini-3.1-pro-preview", temperature=0.1)
structured_llm = llm.with_structured_output(ValidatorOutput)


def _build_directive(proposed: dict, candidate: dict, score) -> dict:
    """Build a merge directive in the shape the Synthesizer's prompt expects."""
    return {
        "proposed_name": proposed.get("name", ""),
        "existing_id": candidate.get("solution_function_id", candidate.get("id", "")),
        "existing_name": candidate.get("name", ""),
        "existing_description": candidate.get("business_description", ""),
        "existing_component_groups": candidate.get("component_groups", []),
        "existing_primary_objects": candidate.get("primary_objects", []),
        "existing_complexity": candidate.get("complexity_score", 0),
        "score": {
            "cg_jaccard": score.cg_jaccard,
            "overlap_coeff": score.overlap_coeff,
            "name_sim": score.name_sim,
            "object_jaccard": score.object_jaccard,
            "cg_set_equality": score.cg_set_equality,
        },
    }


def _detect_overlaps(proposed_functions, resolved_no_merges=None):
    """
    Multi-signal Registry Overlap check (rubric criterion 3).

    Scans the full in-memory registry (hydrated at startup by Fix A) and
    scores each (proposed, candidate) pair with the deterministic scorer
    (CG Jaccard + name similarity + object overlap). Pairs are tiered into
    AUTO_MERGE, GRAY_ZONE (deferred to the adjudicator node), or NO_MERGE.

    Returns (auto_merges, gray_zone_pairs, notes):
      - auto_merges: merge directives for AUTO_MERGE pairs (single-match only;
        multi-match is promoted to gray zone for canonical selection).
      - gray_zone_pairs: deferred pairs for the adjudicator node.
      - notes: human-readable log lines (gray-zone flags, multi-match
        promotions, overlap-coefficient diagnostics).

    Loop terminator (Q9): a proposed function already carrying a non-empty
    solution_function_id has been resolved in a prior pass; skip registry
    scanning for it entirely. Only criteria 1&2 (LLM) still apply.

    Adjudicator memory: (proposed_name, candidate_id) pairs the Adjudicator has
    already ruled NO-MERGE on are skipped for the gray zone, so a distinct pair
    is never re-deferred (and re-adjudicated) on a later retry.
    """
    auto_merges = []
    gray_zone = []
    notes = []

    resolved = {
        (r.get("proposed_name", ""), r.get("candidate_id", ""))
        for r in (resolved_no_merges or [])
    }

    for func in proposed_functions:
        if func.get("solution_function_id"):
            # Already merged into a canonical in a prior pass; do not rescan.
            continue

        prop_auto = []
        prop_gray = []

        for cid, candidate in registry.items():
            candidate_id = candidate.get("solution_function_id", candidate.get("id", ""))
            score = score_pair(func, candidate)
            t = tier(score)

            if t == Tier.AUTO_MERGE:
                prop_auto.append((candidate, score))
            elif t == Tier.GRAY_ZONE:
                if (func.get("name", ""), candidate_id) in resolved:
                    # Adjudicator already ruled these distinct; don't re-defer.
                    continue
                prop_gray.append((candidate, score))
                notes.append(
                    f"'{func['name']}' gray-zone vs '{candidate.get('name', '')}' "
                    f"(CG Jaccard {score.cg_jaccard:.2f}, name_sim {score.name_sim:.1f}, "
                    f"object_jaccard {score.object_jaccard:.2f}, "
                    f"overlap_coeff {score.overlap_coeff:.2f})"
                )

        # Q1: multi-match (>=2 auto-merge candidates) is ambiguous; promote
        # the whole cluster to gray zone for the adjudicator to pick canonical.
        if len(prop_auto) >= 2:
            notes.append(
                f"'{func['name']}' matched {len(prop_auto)} AUTO_MERGE candidates; "
                "promoting to gray zone for canonical selection."
            )
            prop_gray.extend(prop_auto)
            prop_auto = []

        for candidate, score in prop_auto:
            auto_merges.append(_build_directive(func, candidate, score))

        if prop_gray:
            gray_zone.append({"proposed": func, "candidates": prop_gray})

    return auto_merges, gray_zone, notes


def validator_node(state: DomainState) -> Dict[str, Any]:
    """
    Validator Agent (Critic):
    Critiques the proposal against the Tripartite Rubric:
    1. No Orphans (All input component groups are assigned)        -> judged by the LLM
    2. Business Intent & Granularity (outcomes, itemized, no jargon) -> judged by the LLM
    3. Registry Overlap (semantic similarity to existing functions)  -> determined in code

    Criterion 3 is handled deterministically against the in-memory registry
    (hydrated at startup) via the multi-signal scorer in src/dedup/scorer.py,
    so the merge directive (registry_matches) the Synthesizer needs is exact,
    and an already-merged proposal is never falsely rejected for overlap.
    Gray-zone pairs (CG-strong but uncorroborated) are deferred to the
    adjudicator node for LLM resolution.
    """
    proposed_functions = state.get("proposed_functions", [])
    candidate_domain = state.get("candidate_domain", [])
    resolved_no_merges = state.get("resolved_no_merges", [])

    # --- Criterion 3: code-authoritative overlap detection ---
    auto_merges, gray_zone, notes = _detect_overlaps(proposed_functions, resolved_no_merges)
    for note in notes:
        print(f"   [Validator] NOTE: {note}")

    # --- Criteria 1 & 2: LLM judgement (overlap explicitly excluded) ---
    system_prompt = get_system_prompt("validator_system")

    user_prompt = f"""
Input Candidate Domain (Must be fully covered):
{json.dumps(candidate_domain, indent=2)}

Proposed Solution Functions to evaluate:
{json.dumps(proposed_functions, indent=2)}
"""

    print(f"   [Validator] Calling LLM to validate {len(proposed_functions)} proposed functions...")

    response: ValidatorOutput = structured_llm.invoke([
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ])

    # Final validity = criteria 1&2 (LLM) AND no unresolved auto-merges.
    # Gray-zone pairs are deferred to the adjudicator node, which finalizes
    # is_valid after resolving them; if no gray zone exists, this is final.
    provisional = response.is_valid
    is_valid = provisional and not auto_merges
    feedback = response.validation_feedback

    if auto_merges:
        merge_lines = [
            f"- Merge proposed function '{m['proposed_name']}' into existing registry "
            f"function '{m['existing_name']}' (set solution_function_id to "
            f"'{m['existing_id']}', adopt its exact name, and consolidate the "
            f"description and component groups)."
            for m in auto_merges
        ]
        overlap_feedback = "Registry overlap detected. Required merges:\n" + "\n".join(merge_lines)
        # Prepend overlap instructions; keep any criteria-1&2 feedback too.
        feedback = (overlap_feedback + ("\n\n" + feedback if feedback and feedback != "Approved." else "")).strip()
        print(f"   [Validator] {len(auto_merges)} auto-merge(s) detected -> instructing merge.")

    if gray_zone:
        print(f"   [Validator] {len(gray_zone)} proposed function(s) deferred to adjudicator (gray zone).")

    update: Dict[str, Any] = {
        "is_valid": is_valid,
        "validation_feedback": feedback,
        "registry_matches": auto_merges,   # full replace each pass
        "gray_zone_pairs": gray_zone,      # deferred to adjudicator (possibly [])
    }

    # retry_count counts failed validations only. The DomainState reducer is
    # operator.add, so omitting the key on success leaves the count unchanged
    # (a first-pass approval keeps retry_count == 0). The validator increments
    # only for its own failure modes (criteria 1&2 failure or auto-merge
    # directives); the adjudicator increments separately for gray-zone merges.
    # Gray-zone deferral does NOT pre-increment (the adjudicator decides).
    if not is_valid:
        update["retry_count"] = 1

    return update
