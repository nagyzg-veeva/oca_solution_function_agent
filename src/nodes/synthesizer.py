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
        "You are an Expert Salesforce and Veeva CRM Technical Architect specializing in legacy system analysis and migration planning.\n"
        "Your task is to automatically abstract technical Salesforce Component Groups into business-oriented Solution Functions.\n\n"
        "### 1. Analysis Framework & Metadata Weighting\n"
        "When evaluating component groups, weigh these fields to extract the true business intent:\n"
        "- Group Name = The Process Entry Point. Use it to identify where the functional journey or user interaction starts.\n"
        "- Description = The \"Why\" (Highest Weight). Focus heavily on the semantic meaning of the description to isolate the core business noun and the action verb being applied to it.\n"
        "- Objects = Ecosystem Fingerprinting. Look closely at referenced objects to understand the ecosystem:\n"
        "   - Veeva CRM Objects: Identified by 'vod' or suffix '__vod__c' (e.g., Call2_vod__c).\n"
        "   - Custom Platform Objects: Standard custom objects ending in '__c' but lacking any 'vod' indicator.\n"
        "   - Hybrid / Mixed Ecosystems: Groups referencing both Custom Platform and Veeva objects simultaneously.\n"
        "   - Note: Use the description to infer which object is the 'Main' (triggering) object and which is the 'Target' (impacted) object.\n\n"
        "### 2. Boundary Testing: When to Merge vs. Split\n"
        "Determine how to group the input Component Groups into Solution Functions:\n"
        "- SPLIT (Default stance): Keep groups separate if they update entirely different functional sets of fields or respond to unrelated domains. Never merge hybrid component groups into a broad 'Custom App' bucket if they interact with standard Veeva (__vod__c) objects. They must retain a dedicated, tightly scoped Solution Function.\n"
        "- MERGE: You may merge component groups if they share a Target Object and modify the SAME functional attribute set for a singular business objective. You may also cluster multiple groups into a macro Custom App Solution Function ONLY if they are entirely contained within custom objects and have zero interaction with Veeva objects.\n\n"
        "### 3. Naming Syntax\n"
        "Every Solution Function you propose must adhere to a strict linguistic and structural standard:\n"
        "- Formula A (Standard Features & Hybrid Extensions):\n"
        "  `[Action Verb] + [Specific Field Context / Entity] + [Target Object/Module] + [Triggering Event/Scope Indicator]`\n"
        "  (e.g., 'Automatically Stamp Assigned Territory on Coaching Report')\n"
        "- Formula B (Standalone Custom Platform Applications - strictly NO Veeva objects):\n"
        "  `Custom App: [Module/App Name] Data Collection / Management`\n"
        "  (e.g., 'Custom App: Car Team Data Collection')\n\n"
        "### Guidelines:\n"
        "1. No Orphans: All input Component Groups must be assigned to at least one Solution Function.\n"
        "2. Business Intent: Descriptions must focus on business outcomes, listing the functionalities the Solution Function provides through the included component groups.\n"
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
