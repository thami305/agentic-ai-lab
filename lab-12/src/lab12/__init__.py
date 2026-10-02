"""Lab 12 — Client Operations Copilot.

Pipeline: intake -> retrieve -> classify -> propose -> draft -> queue/pause.
Terminal states: resolved | needs_clarification | queued_for_approval | degraded.

The model proposes (draft text, next-step wording); deterministic code decides
(risk classification, routing, terminal states, and every state-changing
action, which only ever runs through the approval queue).
"""
