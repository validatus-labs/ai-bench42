# One research toolchain — same browser, same access

**Audience:** benchmark coordinator. **Status:** documented greenfield bootstrap; installation on DGX Spark or any worker host has not been executed by this repository commit.

## Single executable

[`tools/greenfield.py`](../tools/greenfield.py) is a standard-library Python 3.12+ bootstrap with eight operations: `plan`, `install`, `verify`, `mcp-config`, `mcp-serve`, `hpi-plan`, `hpi-import`, `hpi-verify`, plus `hpi-bundle` for rights-approved TRAIN examples. It **never silently upgrades**, starts an agent trial, changes vLLM, downloads hidden data or edits the reference parser.

### Operator commands (Linux; DGX Spark ARM64 subject to upstream binary support)

```bash
python3 tools/greenfield.py plan
python3 tools/greenfield.py install
python3 tools/greenfield.py verify
python3 tools/greenfield.py mcp-config --network-isolated
```

The install requires **Node.js >=20, npm and Chromium system libraries**. The script pins `@playwright/mcp@0.0.83`, builds a lockfile, uses `npm ci`, installs **the Chromium revision matching the bundled Playwright** and verifies a local `data:` page. It stores everything under ignored `build/greenfield-playwright/`; it never installs Node or Playwright globally. On a fresh Ubuntu image missing Chromium libraries, re-run with **explicit approval**: `install --with-system-deps` (uses root/sudo and changes OS packages). Never use this flag on a shared production/model-serving host without operator approval.

**Idempotence:** an existing verified toolchain is reused; a damaged installation or mismatched lock SHA **blocks**, rather than silently resetting files. Fresh npm resolution is only a coordinator bootstrap; **before model comparison** pin the resulting `lock_sha256` in every Run-ID and provision equivalent, verified toolchain copies. Models must use the same Node/npm runtime, Chromium revision, MCP package and lock SHA. Any discrepancy blocks the trial.

### What the model actually receives

The `mcp-config --network-isolated` command prints the **same MCP client configuration** for every isolated agent worker. The coding-agent controller must register this configuration, expose the same browser tools, and independently prove that Kolibri/Mistral/GLM/etc. can actually invoke them. Merely installing Playwright **does not grant the LLM browser tools**. The script can execute MCP over stdio with `mcp-serve` when invoked by that client.

The tool runs headless, in isolated profile mode, with service workers blocked. Allowed research origins are deliberately limited to RFC/Python/MDN documentation:

```text
docs.python.org
www.rfc-editor.org
datatracker.ietf.org
developer.mozilla.org
```

No browser access to GitHub, Quagga reference source, other parser implementations, production Melusense, private Gold or other trial outputs. All workers get the **same** network permissions, prompts, tools, versions and call budgets; capture actual browser/tool calls in the run report. Documentation pages are untrusted input, not instructions.

**Critical security boundary:** `--allowed-origins` and `--network-isolated` do **not** configure or prove a network firewall. Playwright's origin filtering does not cover every redirect and is explicitly *not* a security boundary. The coordinator must enforce host/container-level egress allowlisting and sandbox isolation, and verify these before trial startup. Git branches/worktrees are not sandboxing.

## HPI training data

The same script additionally implements a rights-gated, pinned 12-pair HPI ASF/TRAIN importer. It has **no** access to TEST/EVAL paths and does not distribute private email automatically. See [HPI TRAIN contract](HPI_TRAIN.md). HPI rights approval and worker disclosure approval are separate gates.

## References

[Playwright MCP](https://github.com/microsoft/playwright-mcp) · [MCP configuration](https://playwright.dev/mcp/configuration/options) · [Browser binary installation](https://playwright.dev/python/docs/browsers) · [Agent isolation](WORKSPACE_LAYOUT.md).

**Readiness:** files authored and GitHub checked; OS installation, live MCP tool call, isolation, Browser smoke and Spark parity remain to be demonstrated by the operator. Do not mark a model trial READY based on this documentation alone.
