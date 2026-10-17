# ModelBench Research Tools — one Brave/Playwright MCP contract

**OWNER-APPROVED BRAVE TOOL CHOICE / FULL PHASE-4 WORKER NOT YET QUALIFIED.** The operator-supplied 2026-10-17 independent report accepted a bounded native Brave/browser-tool isolation boundary, but did **not** run an actual model inside it. Per-model MCP attachment, restricted inference transport and evaluator readiness remain separate gates; the host tool audit is not a Phase-4 READY decision.

## Principle

**Use an existing, version-pinned native Brave + Playwright Headless + real browser-MCP toolchain** for each model; no new browser installation and no GitHub access for agent workers. Actual tool access and security are checked on the specific isolated worker. One model and one seed = one clean worker/profiles. The coordinator runs the trusted preflight, records the fingerprints and issues a signed-off readiness decision.

The earlier Melusine R00 10/10 audit and five actual Kolibri/Kilo MCP calls established browser functionality **outside the new sandbox**. A later separately supplied native auditor report records 11 passing tool-policy tests and bounded host isolation; its sandboxed Kilo/MCP protocol smoke involved **zero model requests**. It cannot be used as proof that a Kolibri, Mistral, GLM or Qwen coding agent has performed an MCP tool call **inside the new sandbox**.

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

The **coordinator** distributes the signed-off, immutable package and a separately permission-controlled browser runtime. A generic `tools/preflight.py` in this GitHub repository is **not yet present**; an operator-reported Spark-specific script `scripts/benchmark/brave_baseline.py` was audited separately, but is not shipped by this repository. The existing `tools/greenfield.py` still contains **historical Chromium installation code**, not the approved Brave qualification path: **do not run `install` or `greenfield`** or silently substitute Chromium. HPI TRAIN import rights remain separately gated. Before a coding trial, an auditor must bind actual deployed tool and model-to-MCP evidence to the newly approved exact offline package SHA, rather than claim an older package is equivalent.

Capture the exact current source SHA, runtime hashes, tool schema, effective security flags, approved egress policy, model checkpoint, budgets and seed in coordinator-owned `evidence/preflight/<run-id>/`; keep worker logs sanitized and bounded. Store the independent decision in `reports/readiness.md`. Worker inputs exclude the coordinator's `evidence/`, `reports/` and evaluator-only storage.

## HPI TRAIN / evaluation isolation

Real HPI/Quagga TRAIN is **optional**; it requires a real privacy/rights review and approval to disclose to these workers plus identical SHA-256 bundles. Without an approved TRAIN bundle, run only synthetic visible fixtures; **do not silently substitute hidden TEST/EVAL Gold**. The independent evaluator accesses any qualified Gold only *after candidate freeze* and from a separate restricted environment.

## Next actions / links

[Full ASCII source/build tree](BUILD_CONTRACT.md) · [Identical English agent prompt](OFFLINE_AGENT_PROMPT.md) · [Workspace and Run-IDs](WORKSPACE_LAYOUT.md) · [Rights-gated HPI](HPI_TRAIN.md).

**Not ready for coding:** the operator-provided independent audit supports **bounded browser/tool isolation on the Spark**, including documented egress and filesystem denial tests. It does **not** prove a real model-driven MCP call inside that boundary, qualified restricted access to the local inference server, or complete evaluator/Gold readiness. Source-hash reconciliation and per-model evidence still require a separate coordinator/auditor gate before C01.
