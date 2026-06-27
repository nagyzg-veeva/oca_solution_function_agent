from typing import Dict, Any
from pydantic import BaseModel, Field
from langchain_google_genai import ChatGoogleGenerativeAI
from src.state.schema import DomainState
from src.vector_store import search_similar_functions
from config.constants import REGISTRY_SEARCH_K, OVERLAP_THRESHOLD
import json

class ValidatorOutput(BaseModel):
    is_valid: bool = Field(description="True if the proposed functions pass criteria 1 (No Orphans) and 2 (Business Intent & Granularity).")
    validation_feedback: str = Field(description="If is_valid is False, provide detailed feedback referencing the specific rubric violation. If True, write 'Approved.'")

llm = ChatGoogleGenerativeAI(model="gemini-3.1-pro-preview", temperature=0.1)
structured_llm = llm.with_structured_output(ValidatorOutput)


def _detect_overlaps(proposed_functions):
    """
    Code-authoritative Registry Overlap check (rubric criterion 3).

    Returns (registry_matches, notes):
      - registry_matches: structured merge directives for proposed functions
        whose closest registry neighbour is at/above OVERLAP_THRESHOLD and that
        are not already merged into that neighbour.
      - notes: human-readable log lines (secondary overlaps, resolved merges).

    A proposed function that already carries the solution_function_id of its
    closest match is treated as an already-resolved merge (loop terminator):
    it is NOT re-flagged, which prevents the merged proposal from overlapping
    itself forever.
    """
    registry_matches = []
    notes = []

    for func in proposed_functions:

        #TESZT 
        test_string = f'{func["name"]} {func["business_description"]}'
        if "DCR".lower() in test_string.lower():
            print("DCR Found")

        results = search_similar_functions(func["business_description"], k=REGISTRY_SEARCH_K)
        if not results:
            continue

        top_doc, top_score = results[0]
        top_id = top_doc.metadata.get("solution_function_id")
        proposed_id = func.get("solution_function_id", "")

        # Loop terminator: already merged into this match.
        if proposed_id and proposed_id == top_id:
            notes.append(
                f"'{func['name']}' already merged into '{top_doc.metadata.get('name')}' "
                f"(id {top_id}); overlap resolved."
            )
            continue

        if top_score >= OVERLAP_THRESHOLD:
            registry_matches.append({
                "proposed_name": func["name"],
                "existing_id": top_id,
                "existing_name": top_doc.metadata.get("name"),
                "existing_description": top_doc.page_content,
                "existing_component_groups": top_doc.metadata.get("component_groups", []),
                "existing_primary_objects": top_doc.metadata.get("primary_objects", []),
                "existing_complexity": top_doc.metadata.get("complexity_score", 0),
                "score": float(top_score),
            })
            # Surface (do not silently drop) secondary above-threshold matches.
            for doc, score in results[1:]:
                if score >= OVERLAP_THRESHOLD:
                    notes.append(
                        f"'{func['name']}' also overlaps '{doc.metadata.get('name')}' "
                        f"(similarity {score:.2f}); v1 merges only the top match."
                    )

    return registry_matches, notes


def validator_node(state: DomainState) -> Dict[str, Any]:
    """
    Validator Agent (Critic):
    Critiques the proposal against the Tripartite Rubric:
    1. No Orphans (All input component groups are assigned)        -> judged by the LLM
    2. Business Intent & Granularity (outcomes, itemized, no jargon) -> judged by the LLM
    3. Registry Overlap (semantic similarity to existing functions)  -> determined in code

    Criterion 3 is handled deterministically against the vector store so the
    merge directive (registry_matches) the Synthesizer needs is exact, and so
    an already-merged proposal is never falsely rejected for overlap.
    """
    proposed_functions = state.get("proposed_functions", [])
    candidate_domain = state.get("candidate_domain", [])

    # --- Criterion 3: code-authoritative overlap detection ---
    registry_matches, notes = _detect_overlaps(proposed_functions)
    for note in notes:
        print(f"   [Validator] NOTE: {note}")

    # --- Criteria 1 & 2: LLM judgement (overlap explicitly excluded) ---
    system_prompt = (
        "You are the Validator Critic for a Veeva CRM/Vault Migration tool.\n"
        "Evaluate the proposed Solution Functions against these two criteria ONLY:\n\n"
        "1. No Orphans: All Component Groups from the Input Candidate Domain MUST be assigned to at least one Proposed Solution Function.\n"
        "2. Business Intent & Granularity: Descriptions MUST focus on business outcomes AND MUST include a clear, itemized list of the discrete functionalities the Solution Function provides. REJECT descriptions that are purely high-level summaries without detailing the specific business capabilities.\n\n"
        "Do NOT consider registry overlap or semantic similarity to existing functions; that is evaluated separately by the system.\n\n"
        "If BOTH criteria pass, set is_valid to True and feedback to 'Approved.'\n"
        "If EITHER criterion fails, set is_valid to False and provide specific, actionable feedback."
    )

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

    # Final validity = criteria 1&2 (LLM) AND no unresolved overlaps (code).
    is_valid = response.is_valid and not registry_matches
    feedback = response.validation_feedback

    if registry_matches:
        merge_lines = [
            f"- Merge proposed function '{m['proposed_name']}' into existing registry "
            f"function '{m['existing_name']}' (set solution_function_id to "
            f"'{m['existing_id']}', adopt its exact name, and consolidate the "
            f"description and component groups)."
            for m in registry_matches
        ]
        overlap_feedback = "Registry overlap detected. Required merges:\n" + "\n".join(merge_lines)
        # Prepend overlap instructions; keep any criteria-1&2 feedback too.
        feedback = (overlap_feedback + ("\n\n" + feedback if feedback and feedback != "Approved." else "")).strip()
        print(f"   [Validator] {len(registry_matches)} overlap(s) detected -> instructing merge.")

    update: Dict[str, Any] = {
        "is_valid": is_valid,
        "validation_feedback": feedback,
        "registry_matches": registry_matches,
    }

    # retry_count counts failed validations only. The DomainState reducer is
    # operator.add, so omitting the key on success leaves the count unchanged
    # (a first-pass approval keeps retry_count == 0).
    if not is_valid:
        update["retry_count"] = 1

    return update
