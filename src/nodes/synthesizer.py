from typing import Dict, Any
from pydantic import BaseModel, Field
from langchain_google_genai import ChatGoogleGenerativeAI
from src.state.schema import DomainState, SolutionFunction
import json

class SolutionFunctionModel(BaseModel):
    name: str = Field(description="The name of the solution function (business focused).")
    business_description: str = Field(description="A business-oriented description of what this function achieves, listing the functionalities the Solution Function provides through the included component groups.")
    primary_objects: list[str] = Field(description="List of primary objects (e.g. Account, Call2_vod__c).")
    component_groups: list[str] = Field(description="List of Component Group IDs assigned to this function. All input component groups must be assigned.")
    complexity_score: int = Field(description="The aggregated complexity score of all assigned component groups.")

class SynthesizerOutput(BaseModel):
    proposed_functions: list[SolutionFunctionModel] = Field(description="List of proposed solution functions derived from the candidate domain.")

# Initialize LLM
llm = ChatGoogleGenerativeAI(model="gemini-3.1-pro-preview", temperature=0.2)
structured_llm = llm.with_structured_output(SynthesizerOutput)

def synthesizer_node(state: DomainState) -> Dict[str, Any]:
    """
    Synthesizer Agent (Builder):
    Analyzes the Candidate Domain and proposes Solution Functions.
    """
    candidate_domain = state.get("candidate_domain", [])
    validation_feedback = state.get("validation_feedback", "")
    
    # Construct the prompt
    system_prompt = (
        "You are a Veeva CRM/Vault Solution Architect. Your task is to automatically abstract technical "
        "Salesforce Component Groups into business-oriented Solution Functions.\n\n"
        "Give a description of the business functionality the Solution Function provides with."
        "Guidelines:\n"
        "1. No Orphans: All input Component Groups must be assigned to at least one Solution Function.\n"
        "2. Business Intent: Descriptions must focus on business outcomes.\n"
    )
    
    user_prompt = f"Here is the Candidate Domain (list of component groups):\n{json.dumps(candidate_domain, indent=2)}\n"
    
    if validation_feedback:
        user_prompt += f"\nPrevious Validation Feedback (Fix these issues):\n{validation_feedback}\n"
    
    user_prompt += "\nPlease propose the Solution Functions based on these guidelines."
    
    print(f"   [Synthesizer] Calling LLM with Candidate Domain ({len(candidate_domain)} groups)...")
    
    # Call LLM
    response: SynthesizerOutput = structured_llm.invoke([
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ])
    
    # Convert Pydantic models back to TypedDict formats for State
    proposed_functions = [
        {
            "name": pf.name,
            "business_description": pf.business_description,
            "primary_objects": pf.primary_objects,
            "component_groups": pf.component_groups,
            "complexity_score": pf.complexity_score
        }
        for pf in response.proposed_functions
    ]
    
    # Return the state update.
    # We increment retry_count by 1
    return {
        "proposed_functions": proposed_functions,
        "retry_count": 1
    }
