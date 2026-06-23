from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

from src.state.schema import DomainState
from src.nodes.synthesizer import synthesizer_node
from src.nodes.validator import validator_node
from src.nodes.hitl import hitl_node
from src.nodes.vault import write_to_vault_node

def route_validation(state: DomainState):
    """
    Routing logic after validation.
    """
    if state.get("is_valid"):
        return "write_to_vault"
    elif state.get("retry_count", 0) >= 3:
        return "hitl_review"  # Max retries hit, trigger human fallback
    else:
        return "synthesize"   # Failed validation but under limit, loop back

# Build the Graph
builder = StateGraph(DomainState)

builder.add_node("synthesize", synthesizer_node)
builder.add_node("validate", validator_node)
builder.add_node("hitl_review", hitl_node)
builder.add_node("write_to_vault", write_to_vault_node)

builder.add_edge(START, "synthesize")
builder.add_edge("synthesize", "validate")

# The conditional edge dictates the loop
builder.add_conditional_edges("validate", route_validation, {"write_to_vault":"write_to_vault", "hitl_review":"hitl_review", "synthesize":"synthesize"})

builder.add_edge("hitl_review", "write_to_vault")
builder.add_edge("write_to_vault", END)

# Compile with a checkpointer to support interrupt()
memory = MemorySaver()
app = builder.compile(checkpointer=memory)

print(app.get_graph().draw_mermaid())

