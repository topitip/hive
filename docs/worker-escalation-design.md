# Worker Escalation Design: Judge → Queen → Operator

## Problem

The previous guardian-subgraph approach had two failure modes:

1. **Never fires** — worker agents ran in a separate TUI context with their own EventBus. The guardian attached to hive_coder's runtime never saw the worker's events.
2. **Too trigger-happy** — when it did fire (e.g. when hive_coder's own execution stalled waiting for user input), it reacted to normal wait states as if they were failures. `exclude_own_graph: False` meant the guardian also fired on hive_coder's own events.

The root cause: reactive event-based monitoring (fire on hard failures) cannot distinguish between "agent is genuinely broken" and "agent is momentarily blocked on user input."

## New Design

Three agents share **one runtime and one EventBus** when a worker is started:

```
One Runtime (shared EventBus)
│
├── Worker Graph (primary)
│   └── EventLoopNode — runs the actual work
│       ↑ logs per step to sessions/{id}/logs/tool_logs.jsonl
│
├── Health Judge Graph (secondary, framework-level reusable)
│   └── Entry point: timer every 2 min → judge_node (event_loop)
│       ├── Reads worker session logs via get_worker_health_summary()
│       ├── Accumulates observations in continuous conversation context
│       ├── Detects: too many RETRYs, stall (no new log steps), doom loops
│       └── If problematic: calls emit_escalation_ticket tool
│           → emits WORKER_ESCALATION_TICKET on shared EventBus
│
└── Queen Graph (secondary, hive_coder ticket_triage)
    └── Entry point: event-driven on WORKER_ESCALATION_TICKET
        ├── ticket_triage_node receives EscalationTicket in memory
        ├── LLM decides: dismiss or intervene
        └── If intervene: calls notify_operator tool
            → emits QUEEN_INTERVENTION_REQUESTED on shared EventBus

TUI
├── Subscribes to QUEEN_INTERVENTION_REQUESTED
├── Shows non-disruptive dismissable overlay (worker keeps running)
└── "Chat with Queen" → split-pane view, queen is interactive
```

## Key Design Decisions

### Judge as event_loop node agent (not inline code)

The health monitor is a proper `event_loop` NodeSpec — same as every other node in the system. This means:
- Its reasoning is transparent (conversation is observable)
- It can deliberate over patterns, not just threshold checks
- It's tunable via its system prompt
- It accumulates state across timer ticks via continuous conversation mode

The conversation IS the judge's memory. No shared memory keys, no external state. The judge reads its own prior messages to track trends: "Last check I saw 47 steps; now I see 52; 5 new steps, 3 RETRY."

### Judge conversation: isolated + continuous

- `isolation_level="isolated"` — judge has its own memory namespace, not polluting the worker's shared memory
- `conversation_mode="continuous"` — conversation persists between timer ticks in `graphs/worker_health_judge/conversations/judge/`

### Structured escalation ticket (not a string)

The judge must fill out a rigorous `EscalationTicket` before escalating. This prevents impulsive escalations. Required fields:

```
ticket_id, created_at
worker_agent_id, worker_session_id, worker_node_id, worker_graph_id
severity: "low"|"medium"|"high"|"critical"
cause: str                    # what the judge observed
judge_reasoning: str          # why it decided to escalate
suggested_action: str         # restart? human review? kill session?
recent_verdicts: list[str]    # last N judge verdicts
total_steps_checked: int
steps_since_last_accept: int
stall_minutes: float|None     # wall-clock since last new log step
evidence_snippet: str         # recent LLM output excerpt
```

### Queen as deliberating intermediary

The queen (hive_coder's `ticket_triage_node`) receives every ticket and must decide: **dismiss or notify the operator**. This adds a second quality gate — the judge might be overly sensitive, and the queen provides a second opinion.

The queen only notifies the operator if the ticket meets intervention criteria. Conservative by design: one unnecessary alert is less costly than alert fatigue.

### Non-disruptive operator notification

`QUEEN_INTERVENTION_REQUESTED` does NOT tear down the worker or force a context switch. The TUI shows a dismissable overlay. The worker keeps running. The operator can choose to connect to the queen's active session for a conversation about the issue.

## New Event Types

| Event | Emitted by | Received by | Purpose |
|-------|-----------|-------------|---------|
| `WORKER_ESCALATION_TICKET` | Health Judge | Queen (event-driven entry point) | Structured ticket delivery |
| `QUEEN_INTERVENTION_REQUESTED` | Queen (notify_operator tool) | TUI | Human operator notification |

## New Files

| File | Purpose |
|------|---------|
| `core/framework/runtime/escalation_ticket.py` | `EscalationTicket` Pydantic schema |
| `core/framework/monitoring/__init__.py` | New framework monitoring package |
| `core/framework/monitoring/worker_health_judge.py` | Health judge graph, node, entry point, goal |
| `core/framework/agents/hive_coder/ticket_receiver.py` | Queen's `TICKET_RECEIVER_ENTRY_POINT` |
| `core/framework/tools/worker_monitoring_tools.py` | `get_worker_health_summary`, `emit_escalation_ticket`, `notify_operator`; `register_worker_monitoring_tools()` |

## Modified Files

| File | Changes |
|------|---------|
| `core/framework/runtime/event_bus.py` | +2 EventTypes, +2 emit methods |
| `core/framework/agents/hive_coder/nodes/__init__.py` | +`ticket_triage_node`, +`ALL_QUEEN_TRIAGE_TOOLS` |
| `core/framework/agents/hive_coder/agent.py` | +`ticket_triage_node` to nodes, +`TICKET_RECEIVER_ENTRY_POINT` to async_entry_points |
| `core/framework/tui/app.py` | `_load_judge_and_queen()`, `QUEEN_INTERVENTION_REQUESTED` handler, split-pane view |

## NOT Modified

- `core/framework/graph/event_loop_node.py` — no inline health check code; monitoring is fully external
- `core/framework/graph/conversation_judge.py` — existing per-iteration quality judge unchanged
- `core/framework/agents/hive_coder/guardian.py` — kept; user-triggered Ctrl+E escalation path still works

## Known Gaps

**Gap 1 — Queen tool starvation.**
The queen's `ticket_triage_node` only has `notify_operator`. If the operator connects and wants the queen to actually fix the worker's code, she'd need file I/O + shell tools. Deferred to a follow-up: dynamically registering the full hive-tools MCP when operator connects.

**Gap 2 — LLM-hang detection latency.**
If the worker's LLM call hangs (never returns), no new log entries are written and no iterations complete. The judge detects this on its next timer tick (≤2 min later). Not zero-latency, but bounded.

**Gap 3 — Worker session_id in judge's context.**
The judge needs the worker's agent_id + session_id to query logs. The timer entry fires with empty input_data. Solution: TUI passes this via the initial session state when loading the judge graph. The worker also writes its session_id to a well-known shared memory key early in execution. Gap: this write doesn't happen automatically today.

**Gap 4 — Dual monitoring channels coexist.**
The old guardian still exists. The new health judge + queen is the primary path. Both can run simultaneously if old code isn't cleaned up. Not a correctness issue, but noisy.

**Gap 5 — Single shared EventBus requirement.**
All three agents (worker, judge, queen) share one EventBus only when loaded in the same runtime via `add_graph`. A separately-started hive_coder session in another TUI window is NOT connected.

## Data Flow

```
Worker iterates → logs ACCEPT/RETRY/CONTINUE to tool_logs.jsonl

Every 2 minutes:
  Health Judge wakes (timer)
  → calls get_worker_health_summary(agent_id, session_id)
  → reads recent verdicts, step counts, timing
  → compares to prior check (from conversation history)
  → if healthy: set_output("health_verdict", "healthy"), done
  → if degraded:
      builds EscalationTicket JSON
      calls emit_escalation_ticket(ticket_json)
      → WORKER_ESCALATION_TICKET published to shared EventBus

Queen's ticket_receiver fires:
  → ticket_triage_node receives ticket in memory key "ticket"
  → LLM reads ticket, applies dismiss/intervene criteria
  → if dismiss: set_output("intervention_decision", "dismissed: ...")
  → if intervene:
      calls notify_operator(ticket_id, analysis, urgency)
      → QUEEN_INTERVENTION_REQUESTED published to shared EventBus

TUI receives QUEEN_INTERVENTION_REQUESTED:
  → shows dismissable overlay (worker is NOT paused)
  → operator chooses:
      "Dismiss" → overlay gone, worker continues
      "Chat with Queen" → split-pane view appears
          worker stream on left, queen conversation on right
          operator can type to queen
          queen can further analyze and provide guidance
```
