# AI-Bench42 — Current state

[Results at a glance](docs/reports/README.md) is the results entrypoint.
[Kolibri: abilities and limits](docs/reports/kolibri.md) gives the concise model
assessment; [methodology](docs/reports/methodology.md) explains conditions,
recorded effort and limits. Historical editions are grouped in the
[evidence index](docs/reports/evidence/README.md); former URLs remain compatibility links.

Kolibri wrote useful tested code and used tools, but no reviewed trial completed
the full parser. Guided work remains separate. No matched local Mistral/GLM
project comparison, completed local SWE-bench score, held-out email accuracy or
measured human-time saving is available. Client output truncation limits the
interpretation of the guided result; it does not explain all implementation defects.

The parser here remains the task starter. Only documentation/navigation changed;
task/API/tests/budgets and benchmark freezes remain unchanged. Report material
must stay outside new worker packages. Per-run receipts and
[the runbook](docs/RUNBOOK.md) govern trial readiness.
