"""
graph.py — Assembles the complete LangGraph call-handling state machine.

Graph topology (one invocation per caller turn):

  START
    └─ check_escalation
         ├─ escalated=True  ──────────────────────────► escalate_node ► END
         └─ escalated=False
              └─ [route_after_check]
                   ├─ current_intent=None      ──► intent_router
                   │      └─ [route_after_intent]
                   │              ├─ "book"       ──► booking_node   ► END
                   │              ├─ "reschedule" ──► identity_gate
                   │              ├─ "cancel"     ──► identity_gate
                   │              ├─ "faq"        ──► faq_node       ► END
                   │              └─ "unclear"    ──► unclear_node
                   │                                    └─ [route_unclear]
                   │                                         ├─ retries<2  ► END
                   │                                         └─ retries>=2 ► escalate_node ► END
                   ├─ "book"          ──────────────► booking_node   ► END
                   ├─ "reschedule" + !verified ──► identity_gate
                   ├─ "reschedule" + verified  ──► reschedule_node  ► END
                   ├─ "cancel"    + !verified  ──► identity_gate
                   ├─ "cancel"    + verified   ──► cancel_node      ► END
                   ├─ "faq"           ──────────────► faq_node       ► END
                   └─ "unclear"       ──────────────► unclear_node
                                                       └─ [route_unclear] ...

  identity_gate → [route_after_identity]
    ├─ verified + reschedule  ──► reschedule_node ► END
    ├─ verified + cancel      ──► cancel_node     ► END
    ├─ !verified + retries<2  ──► END (re-prompt next turn)
    └─ !verified + retries>=2 ──► escalate_node  ► END
"""

from langgraph.graph import StateGraph, START, END
from langgraph.types import RetryPolicy
from agent.state import CallState

# ── Node imports ──────────────────────────────────────────────────────────────
from agent.nodes.check_escalation import check_escalation_node
from agent.nodes.escalate         import escalate_node
from agent.nodes.intent_router    import intent_router_node
from agent.nodes.identity_gate    import identity_gate_node
from agent.nodes.booking          import booking_node
from agent.nodes.reschedule       import reschedule_node
from agent.nodes.cancel           import cancel_node
from agent.nodes.faq              import faq_node
from agent.nodes.unclear          import unclear_node



# ── Routing functions (conditional edges) ────────────────────────────────────

def route_after_check(state: CallState) -> str:
    """Route after escalation check — main dispatcher for all intents."""
    if state.get("escalated"):
        return "escalate_node"

    intent   = state.get("current_intent")
    verified = state.get("identity_verified", False)

    if not intent:
        return "intent_router"
    elif intent == "book":
        return "booking_node"
    elif intent == "reschedule":
        return "identity_gate" if not verified else "reschedule_node"
    elif intent == "cancel":
        return "identity_gate" if not verified else "cancel_node"
    elif intent == "faq":
        return "faq_node"
    elif intent == "unclear":
        return "unclear_node"
    else:
        return "intent_router"


def route_after_intent(state: CallState) -> str:
    """Route after intent is classified — sends to correct handler."""
    intent   = state.get("current_intent")
    verified = state.get("identity_verified", False)

    if not intent or intent == "unclear":
        return "unclear_node"
    elif intent == "book":
        return "booking_node"
    elif intent == "reschedule":
        return "identity_gate" if not verified else "reschedule_node"
    elif intent == "cancel":
        return "identity_gate" if not verified else "cancel_node"
    elif intent == "faq":
        return "faq_node"
    else:
        return END


def route_after_identity(state: CallState) -> str:
    """Route after identity gate — verified or retry or escalate."""
    verified = state.get("identity_verified", False)
    retries  = state.get("identity_retries", 0)
    intent   = state.get("current_intent")

    if verified:
        if intent == "reschedule":
            return "reschedule_node"
        elif intent == "cancel":
            return "cancel_node"
        return END

    if retries >= 2:
        return "escalate_node"

    return END  # re-prompt on next turn


def route_after_unclear(state: CallState) -> str:
    """Route after unclear node — retry or escalate."""
    retries = state.get("intent_retries", 0)
    if retries >= 2:
        return "escalate_node"
    return END


# ── Graph assembly ────────────────────────────────────────────────────────────

def build_graph():
    """Build and compile the LangGraph state machine. Returns a compiled graph."""

    builder = StateGraph(CallState)

    # Register all nodes
    builder.add_node("check_escalation", check_escalation_node)
    builder.add_node("escalate_node",    escalate_node)
    builder.add_node("intent_router",    intent_router_node, retry=RetryPolicy(max_attempts=3))
    builder.add_node("identity_gate",    identity_gate_node, retry=RetryPolicy(max_attempts=3))
    builder.add_node("booking_node",     booking_node)
    builder.add_node("reschedule_node",  reschedule_node)
    builder.add_node("cancel_node",      cancel_node)
    builder.add_node("faq_node",         faq_node, retry=RetryPolicy(max_attempts=3))
    builder.add_node("unclear_node",     unclear_node)

    # Entry point — always check escalation first
    builder.add_edge(START, "check_escalation")

    # After escalation check — main router
    builder.add_conditional_edges(
        "check_escalation",
        route_after_check,
        {
            "escalate_node":  "escalate_node",
            "intent_router":  "intent_router",
            "booking_node":   "booking_node",
            "identity_gate":  "identity_gate",
            "reschedule_node":"reschedule_node",
            "cancel_node":    "cancel_node",
            "faq_node":       "faq_node",
            "unclear_node":   "unclear_node",
        }
    )

    # After intent router — first-time routing
    builder.add_conditional_edges(
        "intent_router",
        route_after_intent,
        {
            "booking_node":   "booking_node",
            "identity_gate":  "identity_gate",
            "reschedule_node":"reschedule_node",
            "cancel_node":    "cancel_node",
            "faq_node":       "faq_node",
            "unclear_node":   "unclear_node",
            END:              END,
        }
    )

    # After identity gate
    builder.add_conditional_edges(
        "identity_gate",
        route_after_identity,
        {
            "reschedule_node": "reschedule_node",
            "cancel_node":     "cancel_node",
            "escalate_node":   "escalate_node",
            END:               END,
        }
    )

    # After unclear node
    builder.add_conditional_edges(
        "unclear_node",
        route_after_unclear,
        {
            "escalate_node": "escalate_node",
            END:             END,
        }
    )

    # All terminal nodes → END
    for node in ["booking_node", "reschedule_node", "cancel_node", "faq_node", "escalate_node"]:
        builder.add_edge(node, END)

    return builder.compile()


# Module-level compiled graph (import this in other modules)
graph = build_graph()
