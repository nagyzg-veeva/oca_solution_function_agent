from typing import Dict, Any
from langgraph.types import interrupt
from src.state.schema import DomainState

def hitl_node(state: DomainState) -> Dict[str, Any]:
    """
    Human-in-the-Loop Node.
    Pauses execution when Builder-Critic loop hits max retries.
    Yields conflict payload to human.
    """
    # This pauses the entire execution and surfaces the conflict payload
    human_decision = interrupt({
        "reason": "Max retries exceeded between Builder and Critic.",
        "candidate_domain": state.get("candidate_domain"),
        "last_proposal": state.get("proposed_functions"),
        "last_critique": state.get("validation_feedback")
    })
    
    # When resumed via Command(resume={...}), the payload will be in human_decision
    return {
        "proposed_functions": human_decision.get("corrected_functions", state.get("proposed_functions")),
        "is_valid": True 
    }
