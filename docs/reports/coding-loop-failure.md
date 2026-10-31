# The coding attempt that exhausted its tool budget

After earlier session/deadline failures, a fresh visible Kolibri attempt ran for
15 minutes 56 seconds and exhausted the unchanged 200-tool limit. More than
33 minutes remained on its overall clock. The final gateway denial was a tool
budget denial, not a wall-time or initial-inference timeout.

The whole-trial ledger recorded 62 requests, 27,459 known generated tokens and
200 tools, with final usage unresolved. Two of five visible verification commands
failed; the delivery report was missing. Independent supplemental probes passed
seven of 27. Detection, MIME, reviewer and safe CLI behavior remained incomplete.

All 131 observed read calls completed. Later diagnosis localized 22 turns reading
the same three unchanged files. Successful reads do not explain why the model
kept choosing them. The underlying behavioral cause remained unproven.

Earlier attempts separately suffered GUI-owned backend termination and transport
or expiry problems. Durable session reconnection and deadline handling were
qualified for future trials; they did not repair this candidate or clear its
uncertain usage. Failure sources were preserved read-only, without replay or
normal success freeze. No held-out scoring was performed.

[Report index](README.md) · [Methods and publication scope](METHODS.md)
