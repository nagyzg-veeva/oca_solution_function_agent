from typing import Dict, Any
from pydantic import BaseModel, Field
from langchain_google_genai import ChatGoogleGenerativeAI
from src.state.schema import DomainState
from src.vector_store import search_similar_functions
import json

class ValidatorOutput(BaseModel):
    is_valid: bool = Field(description="True if the proposed functions pass all criteria in the Tripartite Rubric.")
    validation_feedback: str = Field(description="If is_valid is False, provide detailed feedback on why it failed, referencing the specific rubric violation. If True, write 'Approved.'")

llm = ChatGoogleGenerativeAI(model="gemini-3.1-pro-preview", temperature=0.1)
structured_llm = llm.with_structured_output(ValidatorOutput)

def validator_node(state: DomainState) -> Dict[str, Any]:
    """
    Validator Agent (Critic):
    Critiques the proposal against the Tripartite Rubric:
    1. No Orphans (All input component groups are assigned)
    2. Business Intent (No technical jargon)
    3. Registry Overlap (Checks Vector Store for existing similar functions)
    """
    proposed_functions = state.get("proposed_functions", [])
    candidate_domain = state.get("candidate_domain", [])
    
    # 1. Prepare data for overlap check
    overlap_context = ""
    for func in proposed_functions:
        desc = func["business_description"]
        # Search vector store for top 1 match
        results = search_similar_functions(desc, k=1)
        if results:
            doc, score = results[0]
            # Provide the closest match to the LLM so it can decide if it's > 80% similar
            overlap_context += f"Proposed Function '{func['name']}' closest match in Registry: '{doc.metadata.get('name')}' (Description: '{doc.page_content}', Score: {score})\n"
    
    if not overlap_context:
        overlap_context = "No existing functions in the registry."

    system_prompt = (
        "You are the Validator Critic for a Veeva CRM/Vault Migration tool.\n"
        "You must evaluate the proposed Solution Functions against this strict Tripartite Rubric:\n\n"
        "1. No Orphans: All Component Groups from the Input Candidate Domain MUST be assigned to at least one Proposed Solution Function.\n"
        "2. Business Intent, Naming & Boundaries:\n"
        "   - Descriptions MUST focus on business outcomes. Strictly REJECT any technical jargon (e.g., 'Apex', 'Trigger', 'Visualforce', 'VQL', 'SOQL').\n"
        "   - Naming Syntax MUST be followed:\n"
        "     - Standard/Hybrid functions: `[Action Verb] + [Context/Entity] + [Target Object] + [Event/Scope]`\n"
        "     - Standalone Custom Apps: `Custom App: [Module/App Name]...` (REJECT if this naming is used for functions containing Veeva `__vod__c` objects).\n"
        "   - Boundary Checks: REJECT if the Builder inappropriately merged a Hybrid Extension (touches Veeva objects) into a broad 'Custom App', or merged unrelated data domains. They must be split.\n"
        "3. Registry Overlap: You will be provided with the closest matches from the Global Registry. If a proposed function is extremely semantically similar (>80% overlap in purpose) to an existing registry function, you must REJECT it and tell the Builder to merge with or use the existing one.\n\n"
        "If ALL criteria pass, set is_valid to True and feedback to 'Approved.'\n"
        "If ANY criterion fails, set is_valid to False and provide specific, actionable feedback."
    )
    
    user_prompt = f"""
Input Candidate Domain (Must be fully covered):
{json.dumps(candidate_domain, indent=2)}

Proposed Solution Functions to evaluate:
{json.dumps(proposed_functions, indent=2)}

Registry Overlap Context:
{overlap_context}
"""

    print(f"   [Validator] Calling LLM to validate {len(proposed_functions)} proposed functions...")

    response: ValidatorOutput = structured_llm.invoke([
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ])
    
    return {
        "is_valid": response.is_valid,
        "validation_feedback": response.validation_feedback
    }
