"""Framework-level monitoring components.

Provides reusable monitoring graphs that can be attached to any worker
agent runtime via ``runtime.add_graph()``.

Currently included:
- ``worker_health_judge`` — timer-driven health monitor that reads worker
  session logs, detects degradation patterns, and emits structured
  EscalationTickets to the shared EventBus.
"""

from framework.monitoring.worker_health_judge import (
    HEALTH_JUDGE_ENTRY_POINT,
    judge_goal,
    judge_graph,
    judge_node,
)

__all__ = [
    "HEALTH_JUDGE_ENTRY_POINT",
    "judge_goal",
    "judge_graph",
    "judge_node",
]
