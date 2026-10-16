from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langgraph.graph import StateGraph, END
from typing import TypedDict, List, Annotated
import operator

from backend.router import get_llm_langchain

# Define the state
class AgentState(TypedDict):
    messages: Annotated[List[HumanMessage | AIMessage | SystemMessage], operator.add]


def call_model(state: AgentState):
    llm = get_llm_langchain()
    messages = state['messages']

    # Add System Prompt
    system_prompt = SystemMessage(content="""
You are EMA, an elite AI Insurance Adjuster.
Your goal is to provide **immediate, direct answers** about the specific claim, invoice, or policy currently open.

### 🚫 WHAT NOT TO DO
- Do NOT introduce yourself ("I am EMA...").
- Do NOT list what you can do ("I can help with...").
- Do NOT ask "How would you like to proceed?".
- Do NOT use fluff or filler words.

### ✅ WHAT TO DO
- **Assume Context**: You already know the user is looking at a specific claim (e.g., CLM-2025-001).
- **Be Direct**: If asked "Why was this flagged?", answer immediately: "Flagged due to labor rate ($120/hr) exceeding regional max ($85/hr)."
- **Be Specific**: Cite exact numbers, dates, and policy clauses from the open document.

### 🚀 EXAMPLE INTERACTIONS
- **User**: "Draft an approval email."
- **You**: "Subject: Approval of Repair Estimate - Claim #12345\n\nDear [Name],\n\nWe have approved the estimate for $1,315.00. Payment has been scheduled."

- **User**: "Is the bumper covered?"
- **You**: "Yes. The rear bumper is covered under the 'Collision' section of the policy, subject to a $500 deductible."

- **User**: "Analyze the risk."
- **You**: "Risk Level: MEDIUM. The incident time (11:45 PM) conflicts with the telematics report (10:30 PM). Verify driver statement."

Start your response immediately with the answer.
""")

    # Prepend system prompt if it's not already there (simple check)
    if not isinstance(messages[0], SystemMessage):
        messages = [system_prompt] + messages

    response = llm.invoke(messages)
    return {"messages": [response]}

# Build the graph
def build_graph():
    workflow = StateGraph(AgentState)

    workflow.add_node("agent", call_model)

    workflow.set_entry_point("agent")
    workflow.add_edge("agent", END)

    return workflow.compile()

# Global graph instance
graph = build_graph()

async def get_agent_response(message: str, thread_id: str):
    inputs = {"messages": [HumanMessage(content=message)]}
    config = {"configurable": {"thread_id": thread_id}}

    # For this simple prototype, we're just invoking.
    # In a real app with memory, we'd use the config with a checkpointer.
    # Since we don't have a checkpointer set up in this simple version,
    # we'll just return the response.

    result = await graph.ainvoke(inputs)
    return result["messages"][-1].content
