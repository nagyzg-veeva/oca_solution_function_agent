from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

from src.state.schema import DomainState
from src.nodes.synthesizer import synthesizer_node
from src.nodes.validator import validator_node
from src.nodes.adjudicator import adjudicator_node
from src.nodes.hitl import hitl_node
from src.nodes.vault import write_to_vault_node
from config.constants import MAX_RETRIES

def route_validation(state: DomainState):
    """
    Routing logic after validation (or after adjudication, if it ran).
    """
    if state.get("is_valid"):
        return "write_to_vault"
    elif state.get("retry_count", 0) >= MAX_RETRIES:
        return "hitl_review"  # Max retries hit, trigger human fallback
    else:
        return "synthesize"   # Failed validation but under limit, loop back

def route_after_validate(state: DomainState):
    """
    After the validator runs: if gray-zone pairs were deferred, route to the
    adjudicator; otherwise fall through to the standard validation router.
    """
    if state.get("gray_zone_pairs"):
        return "adjudicate"
    return route_validation(state)

# Build the Graph
builder = StateGraph(DomainState)

builder.add_node("synthesize", synthesizer_node)
builder.add_node("validate", validator_node)
builder.add_node("adjudicate", adjudicator_node)
builder.add_node("hitl_review", hitl_node)
builder.add_node("write_to_vault", write_to_vault_node)

builder.add_edge(START, "synthesize")
builder.add_edge("synthesize", "validate")

# Conditional detour: validate -> adjudicate (if gray zone) else standard route.
builder.add_conditional_edges("validate", route_after_validate, {
    "adjudicate": "adjudicate",
    "write_to_vault": "write_to_vault",
    "hitl_review": "hitl_review",
    "synthesize": "synthesize",
})

# Adjudicator always falls through to the standard router (it has finalized
# is_valid and retry_count for its own failure mode).
builder.add_conditional_edges("adjudicate", route_validation, {
    "write_to_vault": "write_to_vault",
    "hitl_review": "hitl_review",
    "synthesize": "synthesize",
})

builder.add_edge("hitl_review", "write_to_vault")
builder.add_edge("write_to_vault", END)

# Compile with a checkpointer to support interrupt()
memory = MemorySaver()
app = builder.compile(checkpointer=memory)

print(app.get_graph().draw_mermaid())

