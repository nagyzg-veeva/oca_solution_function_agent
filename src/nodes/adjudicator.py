import json
from typing import Dict, Any

from pydantic import BaseModel, Field
from langchain_google_genai import ChatGoogleGenerativeAI

from src.state.schema import DomainState
from src.prompts.loader import get_system_prompt


class AdjudicationResult(BaseModel):
    merge: bool = Field(description="True if the proposed function is the same business function as the canonical candidate.")
    canonical_id: str = Field(description="The candidate id to merge into. Empty string if merge is False.")
    rationale: str = Field(description="One-sentence justification for the decision.")


llm = ChatGoogleGenerativeAI(model="gemini-3.1-pro-preview", temperature=0.0)
structured_llm = llm.with_structured_output(AdjudicationResult)


SYSTEM_PROMPT = get_system_prompt("adjudicator_system")


def _format_prompt(proposed: dict, candidates: list) -> str:
    proposed_block = (
        f"PROPOSED:\n"
        f"  name: {proposed.get('name', '')}\n"
        f"  description: {proposed.get('business_description', '')}\n"
        f"  component_groups: {len(proposed.get('component_groups', []))} groups\n"
        f"  primary_objects: {len(proposed.get('primary_objects', []))} objects\n"
    )
    cand_lines = []
    for c, score in candidates:
        cand_lines.append(
            f"  - id: {c.get('solution_function_id', c.get('id', ''))}\n"
            f"    name: {c.get('name', '')}\n"
            f"    description: {c.get('business_description', '')}\n"
            f"    component_groups: {len(c.get('component_groups', []))} groups\n"
            f"    primary_objects: {len(c.get('primary_objects', []))} objects\n"
            f"    scores: {{cg_jaccard: {score.cg_jaccard:.3f}, "
            f"name_sim: {score.name_sim:.1f}, "
            f"object_jaccard: {score.object_jaccard:.3f}}}"
        )
    candidates_block = "CANDIDATES:\n[\n" + "\n".join(cand_lines) + "\n]"
    return (
        proposed_block
        + "\n"
        + candidates_block
        + "\n\nReturn: { merge: bool, canonical_id: str, rationale: str }"
    )


def _build_directive(proposed: dict, candidate: dict) -> dict:
    return {
        "proposed_name": proposed.get("name", ""),
        "existing_id": candidate.get("solution_function_id", candidate.get("id", "")),
        "existing_name": candidate.get("name", ""),
        "existing_description": candidate.get("business_description", ""),
        "existing_component_groups": candidate.get("component_groups", []),
        "existing_primary_objects": candidate.get("primary_objects", []),
        "existing_complexity": candidate.get("complexity_score", 0),
        "score": None,
    }


def adjudicator_node(state: DomainState) -> Dict[str, Any]:
    gray_zone = state.get("gray_zone_pairs", [])
    if not gray_zone:
        return {"gray_zone_pairs": []}

    print("\n" + "=" * 50)
    print("⚖️  ADJUDICATOR: RESOLVING GRAY-ZONE PAIRS")
    print("=" * 50)

    existing_matches = state.get("registry_matches", [])
    new_merges = []
    new_no_merges = []

    for entry in gray_zone:
        proposed = entry["proposed"]
        candidates = entry["candidates"]
        proposed_name = proposed.get("name", "")
        candidate_ids = [
            (c.get("solution_function_id") or c.get("id", "")) for c, _ in candidates
        ]

        print(f"   [Adjudicator] Adjudicating '{proposed.get('name', '')}' "
              f"against {len(candidates)} candidate(s)...")

        user_prompt = _format_prompt(proposed, candidates)
        try:
            result: AdjudicationResult = structured_llm.invoke([
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ])
        except Exception as e:
            print(f"   [Adjudicator] LLM call failed for '{proposed.get('name', '')}': {e}; treating as no-merge.")
            continue

        if result.merge:
            canonical = next(
                (c for c, _ in candidates
                 if (c.get("solution_function_id") or c.get("id", "")) == result.canonical_id),
                None,
            )
            if canonical:
                new_merges.append(_build_directive(proposed, canonical))
                print(f"   [Adjudicator] MERGE: '{proposed.get('name', '')}' -> "
                      f"'{canonical.get('name', '')}' ({result.rationale})")
            else:
                print(f"   [Adjudicator] WARN: merge=True but canonical_id "
                      f"'{result.canonical_id}' not in candidates; no directive emitted.")
        else:
            # Distinct from every candidate: remember it so the validator does
            # not re-defer this same pair on a later retry.
            new_no_merges.extend(
                {"proposed_name": proposed_name, "candidate_id": cid}
                for cid in candidate_ids
            )
            print(f"   [Adjudicator] NO MERGE: '{proposed.get('name', '')}' "
                  f"({result.rationale})")

    prior_is_valid = state.get("is_valid", False)
    is_valid = prior_is_valid and not new_merges

    update: Dict[str, Any] = {
        "registry_matches": existing_matches + new_merges,
        "gray_zone_pairs": [],
        "is_valid": is_valid,
    }
    if new_no_merges:
        update["resolved_no_merges"] = new_no_merges
    if new_merges:
        update["retry_count"] = 1

    print("=" * 50 + "\n")
    return update
