# First trial: beginner guide

This guide is for the **coordinator**, the person who downloads the project,
prepares the same starting package for each model, starts a qualified worker,
and checks its report. You do not need to know Git branches to prepare the
package. A **commit SHA** is the exact version of the project; a **SHA-256** is
a fingerprint of the package file. A copied folder is **not** an isolated
worker.

The full rules are in the [runbook](RUNBOOK.md). This guide gives commands for
source-package preparation. Continue with the [worker guide](WORKERS.md)
for the supplied launcher, toolchain template and C00 checker. They require
a provisioned, pinned runtime and independently qualified browser/model
channels; package preparation alone does not make a trial `READY`.

## 1. Get the project

Use a Linux terminal with Git, Python 3.12 or newer, `tar` and `sha256sum`.
Run **one command at a time**. This repository may require GitHub access; if
`git clone` asks for access or fails, ask the project administrator for access
or a package with its commit SHA and checksum. Do not paste a password or token
into a command or a report.

```bash
mkdir -p ~/ai-bench42-workspace
```

```bash
cd ~/ai-bench42-workspace
```

```bash
git clone https://github.com/validatus-labs/ai-bench42.git
```

```bash
cd ai-bench42
```

```bash
python3 --version
```

If Python is older than 3.12, stop before running project commands.

## 2. Pin an exact source version

```bash
git status --short
```

This must print **nothing** for a fresh checkout. If it lists changed files,
stop and resolve them; an archive made from a commit does not include local
edits or new untracked files.

```bash
PINNED_SHA="$(git rev-parse HEAD)"
```

```bash
printf '%s\n' "$PINNED_SHA"
```

The output is the 40-character source version to record in the run manifest.
For a scored trial, the coordinator must first agree which reviewed commit SHA
all models will use. The command above records the currently checked-out
commit; it does not approve that commit by itself. To use an agreed SHA, set
`PINNED_SHA` to it, then run `git switch --detach "$PINNED_SHA"` and check
`git status --short` again.

## 3. Make and check the Git-free package

Run these commands from the project folder:

```bash
mkdir -p build/packages
```

```bash
PACKAGE="build/packages/source-${PINNED_SHA}.tar"
```

```bash
git archive --format=tar --output="$PACKAGE" "$PINNED_SHA"
```

```bash
(cd build/packages && sha256sum "source-${PINNED_SHA}.tar" > "source-${PINNED_SHA}.tar.sha256")
```

```bash
(cd build/packages && sha256sum -c "source-${PINNED_SHA}.tar.sha256")
```

The last command must print `OK`. Keep the `.tar` and `.sha256` together when
copying them. On another machine, put them in one folder, enter that folder,
and run `sha256sum -c source-<the-same-SHA>.tar.sha256` **before** extracting.
`git archive` includes only files committed at `PINNED_SHA`; it excludes `.git`,
ignored and untracked data, and the coordinator's local edits. Review the
committed file list before sharing, because Git would also archive any secret
accidentally committed. This package does not pin the model or browser tools.

For a harmless preview, unpack into a folder that is **not** a worker:

```bash
mkdir -p build/package-preview
```

```bash
tar -xf "$PACKAGE" -C build/package-preview
```

```bash
ls build/package-preview
```

You should see `AGENTS.md`, `TASKS.md`, `melusense/`, `tests/` and `docs/`.
The archive and preview live under ignored `build/`; do not add them to Git.

## 4. Understand the boundary before starting a model

Each model and seed needs its **own** workspace and Run-ID. The worker must
only see that workspace, visible tests and explicitly approved TRAIN examples.
It must not see the coordinator's checkout, `.git`, sibling runs, host home,
credentials, private reference code, hidden tests or Gold. The browser needs
the same pinned Brave/Playwright MCP tools and controlled public-web access in
every trial. Model inference uses a separately restricted connection.

Copying the archive to a new folder, using a Git branch, or opening Kilo in
that folder does **not** prove these boundaries. The coordinator must first
complete every [C00 preflight check](RUNBOOK.md#c00-qualify-one-worker-before-c01)
from inside the actual worker, record the model/seed, source SHA, archive
SHA-256, tool hashes and allowed access, and produce a per-run `READY` receipt.
The [worker guide](WORKERS.md#1-fill-a-private-toolchain-configuration) gives
the `prepare`, `probe`, `preflight.py` and `run` commands. Fill and verify the
target toolchain first; the supplied template has no invented hashes or
gateway qualification. Until C00 succeeds, the state remains
**package prepared, trial not qualified**.

The fixed real [HPI TRAIN examples](HPI_TRAIN.md) are required for every Phase-4
model and seed. Complete the rights/privacy and worker-disclosure review, then
follow the protocol's `hpi-import`, `hpi-verify` and `hpi-bundle` commands.
Record the identical bundle SHA-256 for every run. Without approval or the
verified bundle, stop before C01. Visible synthetic fixtures supplement these
examples. Each worker must run its parser on all 12 TRAIN examples and report
the results.
After C00 is `READY`, give the worker the unchanged
[coding-agent prompt](OFFLINE_AGENT_PROMPT.md). The independent evaluator alone
runs protected tests after the candidate is frozen.
