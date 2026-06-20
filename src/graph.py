from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
from src.state.schema import DomainState
from src.agents.synthesizer import synthesizer_node
from src.agents.validator import validator_node
from src.agents.hitl import hitl_node

def write_to_vault_node(state: DomainState):
    # Placeholder for Vault write logic and Vector DB update
    return state

def route_validation(state: DomainState):
    if state.get("is_valid"):
        return "write_to_vault"
    elif state.get("retry_count", 0) >= 3:
        return "hitl_review"
    else:
        return "synthesize"

def create_graph():
    builder = StateGraph(DomainState)

    builder.add_node("synthesize", synthesizer_node)
    builder.add_node("validate", validator_node)
    builder.add_node("hitl_review", hitl_node)
    builder.add_node("write_to_vault", write_to_vault_node)

    builder.add_edge(START, "synthesize")
    builder.add_edge("synthesize", "validate")

    builder.add_conditional_edges("validate", route_validation)

    builder.add_edge("hitl_review", "write_to_vault")
    builder.add_edge("write_to_vault", END)

    memory = MemorySaver()
    return builder.compile(checkpointer=memory)