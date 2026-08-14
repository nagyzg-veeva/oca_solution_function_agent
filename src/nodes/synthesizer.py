from typing import Dict, Any
from pydantic import BaseModel, Field
from langchain_google_genai import ChatGoogleGenerativeAI
from src.state.schema import DomainState, SolutionFunction
import json
from src.prompts.loader import get_system_prompt

class SolutionFunctionModel(BaseModel):
    solution_function_id: str = Field(default="", description="Leave empty for a new function. When merging into an existing registry function (per Required Merges), set this to the existing function's id.")
    name: str = Field(description="The name of the solution function (business focused). When merging, use the exact name of the existing registry function.")
    business_description: str = Field(description=(
        "A comprehensive, business-oriented description that includes a clear, itemized list of the discrete "
        "functionalities this Solution Function provides. Must be easily understood by a Business Analyst without "
        "technical jargon. "
        "FORMAT AS VALID MARKDOWN: write the intro sentence, then a blank line, then the itemized capabilities as a "
        "Markdown unordered list where EACH item is on its own line and starts with '- ' (hyphen + space). "
        "Do NOT use the '•' bullet character and do NOT put multiple items on one line. "
        "Example:\\n"
        "Tracks customer call interactions. Key capabilities include:\\n"
        "\\n"
        "- Calculates total annual submitted calls\\n"
        "- Populates the most recent interaction date"
    ))
    primary_objects: list[str] = Field(description="List of primary objects (e.g. Account, Call2_vod__c).")
    component_groups: list[str] = Field(description="List of Component Group IDs assigned to this function. All input component groups must be assigned.")
    complexity_score: int = Field(description="The aggregated complexity score of all assigned component groups.")

class SynthesizerOutput(BaseModel):
    proposed_functions: list[SolutionFunctionModel] = Field(description="List of proposed solution functions derived from the candidate domain.")

# Initialize LLM. temperature=0.0: on retries the synthesizer must make
# *minimal, targeted* edits to its prior proposal (apply merges, fix feedback)
# rather than re-derive the decomposition from scratch. Any drift in names /
# component-group assignments between passes re-triggers overlap detection and
# prevents the Builder-Critic loop from converging, so determinism matters here.
llm = ChatGoogleGenerativeAI(model="gemini-3.6-flash", temperature=0.0, maxOutputTokens=65536)
structured_llm = llm.with_structured_output(SynthesizerOutput, include_raw=True)

def synthesizer_node(state: DomainState) -> Dict[str, Any]:
    """
    Synthesizer Agent (Builder):
    Analyzes the Candidate Domain and proposes Solution Functions.
    """
    candidate_domain = state.get("candidate_domain", [])
    validation_feedback = state.get("validation_feedback", "")
    registry_matches = state.get("registry_matches", [])
    prior_functions = state.get("proposed_functions", [])
    is_retry = bool(prior_functions)

    # Construct the prompt
    system_prompt = get_system_prompt("synthesizer_system")

    user_prompt = f"Here is the Candidate Domain (list of component groups):\n{json.dumps(candidate_domain, indent=2)}\n"

    if is_retry:
        # Feed the prior proposal back so this pass is an incremental EDIT, not a
        # regeneration. Without this the synthesizer is stateless: it re-derives
        # a different decomposition each loop, so merge directives point at
        # functions it no longer produces and new overlaps keep appearing — the
        # loop never converges. Keep untouched functions byte-for-byte identical
        # (same id, name, description, component_groups) so the validator's
        # already-resolved short-circuit holds.
        user_prompt += (
            "\nYour PREVIOUS proposal (revise this — do NOT start over):\n"
            f"{json.dumps(prior_functions, indent=2)}\n"
            "\nApply ONLY the targeted changes below. Every function not "
            "referenced by the feedback or the Required Merges MUST be returned "
            "UNCHANGED — identical solution_function_id, name, description, "
            "primary_objects, and component_groups.\n"
        )

    if validation_feedback:
        user_prompt += f"\nValidation Feedback (fix exactly these issues):\n{validation_feedback}\n"

    if registry_matches:
        user_prompt += (
            "\nRequired Merges (existing registry functions to merge the listed "
            "proposals into — adopt their id and name, consolidate descriptions "
            f"and component groups):\n{json.dumps(registry_matches, indent=2)}\n"
        )

    user_prompt += (
        "\nReturn the updated proposal."
        if is_retry
        else "\nPlease propose the Solution Functions based on these guidelines."
    )
    
    print(f"   [Synthesizer] Calling LLM with Candidate Domain ({len(candidate_domain)} groups)...")
    
    # Call LLM
    raw_response = structured_llm.invoke([
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ])

    usage = (raw_response.get("raw").usage_metadata or {}) if raw_response.get("raw") else {}
    meta = raw_response.get("raw").response_metadata or {} if raw_response.get("raw") else {}
    print(f"   [Synthesizer] Raw message: content_len={len(raw_response.get('raw').content) if raw_response.get('raw') else -1}, "
          f"num_tool_calls={len(raw_response.get('raw').tool_calls) if raw_response.get('raw') else -1}")
    print(f"   [Synthesizer] finish_reason={meta.get('finish_reason')} | safety_ratings_present={'safety_ratings' in meta} | "
          f"response_metadata_keys={sorted(meta.keys())}")
    print(f"   [Synthesizer] Usage: input_tokens={usage.get('input_tokens')}, output_tokens={usage.get('output_tokens')}, "
          f"total_tokens={usage.get('total_tokens')}")

    if raw_response.get("parsing_error"):
        raw = raw_response.get("raw")
        print(f"   [Synthesizer] PARSING ERROR: {raw_response['parsing_error']}")
        print(f"   [Synthesizer] Raw content (first 2000 chars):\n{str(getattr(raw, 'content', raw))[:2000]}")
        print(f"   [Synthesizer] Tool call args summary (ids/keys):")
        for call in getattr(raw, "tool_calls", []) or []:
            args = call.get("args", {}) if isinstance(call, dict) else getattr(call, "args", {})
            funcs = args.get("proposed_functions", [])
            keys_seen = set()
            for f in funcs:
                keys_seen.update(f.keys())
            print(f"      call '{call.get('id', '?')}': n_functions={len(funcs)}, set_of_keys={sorted(keys_seen)}")
            for i, f in enumerate(funcs):
                missing = set(SolutionFunctionModel.model_fields.keys()) - set(f.keys())
                if missing:
                    print(f"      function[{i}] id={f.get('solution_function_id', '?')} name={f.get('name', '?')[:60]!r} MISSING={sorted(missing)}")
        raise raw_response["parsing_error"]

    response: SynthesizerOutput = raw_response["parsed"]
    
    # Convert Pydantic models back to TypedDict formats for State
    proposed_functions = [
        {
            "solution_function_id": pf.solution_function_id,
            "name": pf.name,
            "business_description": pf.business_description,
            "primary_objects": pf.primary_objects,
            "component_groups": pf.component_groups,
            "complexity_score": pf.complexity_score
        }
        for pf in response.proposed_functions
    ]
    
    # Return the state update.
    # The retry counter is owned by the validator (incremented only on a
    # failed validation), so the synthesizer does not touch it here.
    return {
        "proposed_functions": proposed_functions
    }
