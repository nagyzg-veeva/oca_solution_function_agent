from langgraph.types import interrupt
from src.state.schema import DomainState

def hitl_node(state: DomainState):
    """
    Human-in-the-Loop Node: Pauses execution for human review when retry limit is reached.
    """
    human_decision = interrupt({
        "reason": "Max retries exceeded.",
        "domain": state["candidate_domain"],
        "last_proposal": state.get("proposed_functions", []),
        "last_critique": state.get("validation_feedback", "")
    })
    
    return {
        "proposed_functions": human_decision.get("corrected_functions", []),
        "is_valid": True 
    }