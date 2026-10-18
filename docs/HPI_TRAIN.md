# HPI / Quagga — TRAIN-only data contract

**Purpose:** give every coding agent the *same*, independently annotated real-world development examples, without leaking protected TEST/EVAL material or reference implementations.

The fixed TRAIN import, hash verification, worker bundle and parser checks on
all 12 examples are **required for every Phase-4 model and seed**. The same
bundle SHA-256 must be recorded for every run in the comparison. Missing rights
or worker-disclosure approval, missing data or a different bundle blocks C00;
synthetic fixtures supplement these examples and cannot replace them.

## Exact provenance

- [HPI Quagga dataset](https://github.com/HPI-Information-Systems/Quagga/tree/4ba5be0fd4a0a5954527ea93cf6592f54f4fc3f0/Datasets).
- Source commit: `4ba5be0fd4a0a5954527ea93cf6592f54f4fc3f0` (immutable full SHA).
- Only `Datasets/ASF/train`; **12 original body files + 12 matching `.ann` files**. The list and Git blob SHA-1 for each are hard-coded in [`tools/greenfield.py`](../tools/greenfield.py).
- Example: [message `train_1088`](https://github.com/HPI-Information-Systems/Quagga/blob/4ba5be0fd4a0a5954527ea93cf6592f54f4fc3f0/Datasets/ASF/train/train_1088) and [annotation `train_1088.ann`](https://github.com/HPI-Information-Systems/Quagga/blob/4ba5be0fd4a0a5954527ea93cf6592f54f4fc3f0/Datasets/ASF/train/train_1088.ann).
- Selected examples include both **historical Header annotations and examples without Header annotations**. This is a tiny controlled development set, **not** a representative multilingual benchmark.

These .ann files contain `text` plus typed `denotations` with **Unicode codepoint** `start/end` offsets into **`ann.text`**. For some source files, `ann.text` differs from the raw text file. Never score against raw RFC-822 bytes or silently normalize text and claim the offsets are unchanged. HPI's zones `Header`, `Body` and `Body/Signature` are **not exactly equivalent** to Melusense's reply/forward/signature/footer target classes; define any mapping separately.

## Safe, repeatable commands

```bash
python3 tools/greenfield.py hpi-plan
# Only after a human legal/privacy review; file is private and OUTSIDE Git:
python3 tools/greenfield.py hpi-import --rights-record /private/hpi-rights.json
python3 tools/greenfield.py hpi-verify
# Required: worker-visible, deterministic annotated-text TRAIN bundle;
# requires explicit reviewer approval for correspondence disclosure:
python3 tools/greenfield.py hpi-bundle \
  --rights-record /private/hpi-rights.json --approve-worker-disclosure
```

The private approval JSON must contain `approved=true`, `source_revision` equal to the full SHA above, `usage="internal-train-only"`, and genuine `reviewer` / `legal_basis` fields documenting a completed review. **Do not manufacture an approval simply to make the importer run.**

The importer downloads only approved URLs from that exact commit and verifies **original Git blob hashes + generated SHA-256 hashes**. Repeat imports verify the same files instead of overwriting. `hpi-bundle` emits a byte-stable private `build/hpi-train-visible.jsonl` with `ann.text` and typed TRAIN-only spans; copy the **identical SHA-256 bundle** into each equally restricted coding-agent sandbox, never a private EVAL set. The bundle must be explicitly rights-cleared because it contains real correspondence. Outputs stay under ignored private directories and are not pushed to GitHub or sent to external model services.

## From real mail examples to a parser result

The coordinator imports the **fixed set of real HPI/Quagga TRAIN mail texts
and annotations** through `tools/greenfield.py hpi-import` after rights and
privacy approval. `hpi-import` downloads the fixed files, `hpi-verify` checks
them, and `hpi-bundle` packages the approved examples for every worker. All
three steps are required. None of these
commands runs or grades a candidate parser. The script's separate `install`
and `greenfield` commands are historical Chromium setup paths, not the
approved Brave workflow.

```text
Rights/privacy approval -> fixed HPI TRAIN import -> hash verification
                                           |
                                           v
                       required identical TRAIN bundle for each worker
                                           |
                                           v
                        build parser + run visible synthetic tests
                        + check parser on all 12 TRAIN examples
                                           |
                                           v
                                freeze each candidate
                                           |
                                           v
                 independent, held-out real-mail evaluation if qualified
```

Every worker receives the same approved TRAIN bundle after correspondence
disclosure is approved. Each worker must inspect the mail text and annotations,
run its parser on all 12 examples, and record per-example results and failures
in its report. Include the bundle SHA-256 and the mapping used for any label
comparisons so these checks can be compared across models and seeds.
HPI's annotation classes and text coordinates need an explicit mapping before
any score is claimed: compare against `ann.text` coordinates and document how
HPI zones map to Melusense categories. TRAIN observations are development
evidence, not independent test results.

After candidate freeze, an independent evaluator alone runs protected hidden
tests and rights-cleared held-out Gold. Without approved TRAIN data, the
Phase-4 trial cannot start. Without qualified held-out Gold, real-mail accuracy is
`NOT_EVALUATED`. The benchmark is [not yet started](../TASKS.md). This workflow
does not assert that the mails have already been downloaded or a parser has
passed.

## Independent scoring

A developer may inspect authorized TRAIN examples and visible labels. The coordinator operates the trial and checks reports; only the **separate evaluator runtime** receives properly licensed, independently held-out HPI TEST/EVAL or separate adjudicated Gold. Never tune on these data or reveal them to workers. Public Quagga source pages may be researched under the [Brave research policy](RUNBOOK.md#public-research-through-brave), but private benchmark reference implementations remain inaccessible. All candidates freeze before evaluator-only scoring, with exact coordinates and valid class mapping documented. Missing rights, Gold or split isolation = **BLOCKED / NOT_EVALUATED**, not 100% recall.

**Important:** The Quagga repository's public code license does **not by itself** prove unrestricted privacy, training or redistribution rights for all third-party emails. A rights and purpose assessment is mandatory.
