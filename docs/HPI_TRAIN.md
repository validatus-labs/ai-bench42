# HPI / Quagga — TRAIN-only data contract

**Purpose:** give every coding agent the *same*, independently annotated real-world development examples, without leaking protected TEST/EVAL material or reference implementations.

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
# Optional: worker-visible, deterministic annotated-text TRAIN bundle;
# requires explicit reviewer approval for correspondence disclosure:
python3 tools/greenfield.py hpi-bundle \
  --rights-record /private/hpi-rights.json --approve-worker-disclosure
```

The private approval JSON must contain `approved=true`, `source_revision` equal to the full SHA above, `usage="internal-train-only"`, and genuine `reviewer` / `legal_basis` fields documenting a completed review. **Do not manufacture an approval simply to make the importer run.**

The importer downloads only approved URLs from that exact commit and verifies **original Git blob hashes + generated SHA-256 hashes**. Repeat imports verify the same files instead of overwriting. `hpi-bundle` emits a byte-stable private `build/hpi-train-visible.jsonl` with `ann.text` and typed TRAIN-only spans; copy the **identical SHA-256 bundle** into each equally restricted coding-agent sandbox, never a private EVAL set. The bundle must be explicitly rights-cleared because it contains real correspondence. Outputs stay under ignored private directories and are not pushed to GitHub or sent to external model services.

## Independent scoring

A developer may inspect authorized TRAIN examples and visible labels. Only the **coordinator/evaluator** may acquire properly licensed, independently held-out HPI TEST/EVAL or separate adjudicated Gold; never tune on these data, reveal them to workers, or give workers the HPI parser/Quagga implementation. All candidates freeze before evaluator-only scoring, with exact coordinates and valid class mapping documented. Missing rights, Gold or split isolation = **BLOCKED / NOT_EVALUATED**, not 100% recall.

**Important:** The Quagga repository's public code license does **not by itself** prove unrestricted privacy, training or redistribution rights for all third-party emails. A rights and purpose assessment is mandatory.
