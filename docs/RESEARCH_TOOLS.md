# ModelBench Research Tools — one Brave/Playwright MCP contract

**OWNER-APPROVED BRAVE TOOL CHOICE / NOT YET RUNTIME-QUALIFIED.** This is the intended offline Brave-based research-tool contract. Approval of the task does not prove that any DGX Spark benchmark worker is isolated or READY.

## Principle

**Use an existing, version-pinned native Brave + Playwright Headless + real browser-MCP toolchain** for each model; no new browser installation and no GitHub access for agent workers. Actual tool access and security are checked on the specific isolated worker. One model and one seed = one clean worker/profiles. The coordinator runs the trusted preflight, records the fingerprints and issues a signed-off readiness decision.

A five-call Kolibri/Kilo host-open MCP smoke was reported, as was the previous Melusine R00 independent 10/10 Brave audit. Those show technical browser functionality **in that environment only**, not benchmark worker confinement or cross-model parity.

## Evidence available for coordinator requalification (not approved global pins)

| Runtime | Previously observed, not yet qualified per benchmark worker |
| --- | --- |
| Browser | Native Brave 155.0.8059.80, binary `/opt/brave.com/brave/brave` |
| MCP | Node MCP package version 0.0.83 (full module seal reported) |
| Node | v24.22.0 on the reported host |
| Playwright | Node Playwright/core 1.64.0-alpha-1790635538000 |
| Kilo extension | 7.8.12, host-open background MCP client (not a sandbox) |
| Additional Python Playwright | Separate installed environment, not proof of active Node-MCP version |

These reported values are an **inventory lead** only. The coordinator must obtain authoritative absolute paths, SHA-256 hashes, complete tool schema/config, process/mount/namespace routing, package lock or package set, effective browser args and model->MCP invocation logs **from the actual candidate worker**. If any required data is missing, report `BLOCKED`, not `PASS`.

## Qualify before C01

1. Verify the transferred Git-free offline starter archive SHA-256 and file-hash manifest; preserve the original model/P1–P3 receipts and report their scoped status.
2. Verify Brave binary and installed Playwright/MCP/Node identities and exact SHA256; prove headless mode, namespace/Seccomp browser sandbox, separate ephemeral profile, no remote debug listener, no personal profile/cookies, no downloads, bounded pages and no service-worker registration.
3. Verify that **this exact coding agent** can invoke real approved browser MCP tools: load a harmless local `data:` page, inspect a marker and close the tab. Browser launch from Python alone or a `connected` label is insufficient.
4. Browser research is limited to **exact approved documentation origins**:
   - `https://docs.python.org`
   - `https://www.rfc-editor.org`
   - `https://datatracker.ietf.org`
   - `https://developer.mozilla.org`
5. Verify default-deny effective worker egress outside the allowlist, including redirects, DNS, IPv4 and IPv6. A browser `--allowed-origins` flag **is not a firewall**. Use non-sensitive denied test targets; never probe private Gold or reference code contents.
6. Verify the worker may see and write only its own `/workspace`; it cannot access the coordinator root, sibling runs, GitHub credentials, host HOME, source references, private corpora, any HPI TEST/EVAL, hidden evaluator or Gold. Run independent negative filesystem permission probes without reading private contents. The native Brave renderer sandbox is not equivalent to an agent filesystem sandbox.
7. Require identical runtime versions/config/allowed tool calls and budgets for all eligible model workers. Record a model-issued browser call for each model; Kolibri alone does not qualify Mistral/GLM.
8. If a gate fails or an unknown configuration is found: write a sanitized `BLOCKED` or `DEVIATION` receipt, do not install, reset, grant access, downgrade a policy or launch C01–C07.

## Deployment and reproducibility

The **coordinator** distributes the signed-off, immutable package and a separately permission-controlled browser runtime. A planned `tools/preflight.py` would check the existing runtime without mutation; it is **not deployed yet**. The earlier `tools/greenfield.py` script on this draft's source tree retains **legacy Chromium install code**. **Do not execute its `install` or `greenfield` operation for the Brave benchmark** or silently substitute Chromium; keep HPI TRAIN import capability gated by explicit rights. A new, reviewed read-only Brave checker and tests are required before this draft can become a freeze.

Capture the exact current source SHA, runtime hashes, tool schema, effective security flags, approved egress policy, model checkpoint, budgets and seed in coordinator-owned `evidence/preflight/<run-id>/`; keep worker logs sanitized and bounded. Store the independent decision in `reports/readiness.md`. Worker inputs exclude the coordinator's `evidence/`, `reports/` and evaluator-only storage.

## HPI TRAIN / evaluation isolation

Real HPI/Quagga TRAIN is **optional**; it requires a real privacy/rights review and approval to disclose to these workers plus identical SHA-256 bundles. Without an approved TRAIN bundle, run only synthetic visible fixtures; **do not silently substitute hidden TEST/EVAL Gold**. The independent evaluator accesses any qualified Gold only *after candidate freeze* and from a separate restricted environment.

## Next actions / links

[Full ASCII source/build tree](BUILD_CONTRACT.md) · [Identical English agent prompt](OFFLINE_AGENT_PROMPT.md) · [Workspace and Run-IDs](WORKSPACE_LAYOUT.md) · [Rights-gated HPI](HPI_TRAIN.md).

**Not ready:** existing Brave works, but browser policy and **effective isolated worker/gateway egress/reference denial** have not yet been proven. Only the Owner and independent auditor may approve a new exact frozen SHA for Phase 4.
