"""Structured escalation ticket emitted by the Worker Health Judge.

The ticket is the required artifact that the judge must fill out before
escalating an issue to the Queen. Requiring this structured form prevents
impulsive escalations — the judge must articulate the cause, evidence,
severity, and a suggested action before anything is emitted.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field


class EscalationTicket(BaseModel):
    """A structured escalation report from the Worker Health Judge.

    The judge fills this out when it observes a degradation pattern in
    the worker agent's execution. The Queen receives this ticket and
    decides whether to notify the human operator.
    """

    # Identity
    ticket_id: str = Field(default_factory=lambda: str(uuid4()))
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())

    # Worker identification
    worker_agent_id: str = Field(description="Agent ID of the monitored worker")
    worker_session_id: str = Field(description="Active session ID being monitored")
    worker_node_id: str = Field(description="Node ID where the issue is occurring")
    worker_graph_id: str = Field(description="Graph ID of the worker")

    # Problem characterization — filled by judge via LLM reasoning
    severity: Literal["low", "medium", "high", "critical"] = Field(
        description="Severity of the detected issue"
    )
    cause: str = Field(
        description=(
            "Human-readable description of what the judge observed. "
            "Example: 'Node has produced 18 consecutive RETRY verdicts with no progress.'"
        )
    )
    judge_reasoning: str = Field(
        description="The judge's deliberation chain: why it decided to escalate vs dismiss."
    )
    suggested_action: str = Field(
        description=(
            "What the judge recommends. Examples: "
            "'Restart the node', 'Check API credentials', "
            "'Review system prompt for logic errors', 'Kill session'."
        )
    )

    # Evidence — quantitative signals the Queen can evaluate
    recent_verdicts: list[str] = Field(
        default_factory=list,
        description="Last N judge verdicts (ACCEPT/RETRY/CONTINUE/ESCALATE) in order.",
    )
    total_steps_checked: int = Field(
        default=0,
        description="Total number of log steps the judge examined in this check.",
    )
    steps_since_last_accept: int = Field(
        default=0,
        description="How many consecutive steps have passed without an ACCEPT verdict.",
    )
    stall_minutes: float | None = Field(
        default=None,
        description=(
            "Wall-clock minutes since the last new log step was written. "
            "None if the worker is actively producing steps."
        ),
    )
    evidence_snippet: str = Field(
        default="",
        description=(
            "Brief excerpt from the worker's most recent LLM output or error message. "
            "Used by the Queen to assess context without reading the full log."
        ),
    )
