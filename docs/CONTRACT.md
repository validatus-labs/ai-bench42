# Candidate API and safety contract

Implement `melusense.detect_text(text: str, locale: str = "auto", *, ml_mode: str = "off") -> dict` and
`melusense.detect_eml(raw: bytes, locale: str = "auto", *, ml_mode: str = "off") -> dict`.

Both return JSON-compatible data with:

- `schema_version`: integer 1.
- `source_sha256`: SHA-256 of exact UTF-8 text bytes or original EML bytes.
- `source_kind`: `text` or `eml`.
- `text`: original text unchanged for detect_text; deterministic decoded selected
  body for detect_eml, with provenance/mapping limitations explicitly reported.
- `candidates`: list of `{kind, start, end, evidence}`; kind is reply, forward,
  signature or footer; indices are Unicode code points in returned text, half-open,
  bounded and nonempty. Preserve CRLF and never invent raw-byte equivalence.
- `authorized_removals`: list, empty by default. An observed header/signature,
  confidence score, HTML marker or dictionary hit never grants deletion authority.
- `attachments`: list of inert metadata records; at least filename, media_type,
  size_bytes and part_id. Do not store payloads in result, logs or exported files.
- `warnings`: list of deterministic machine-readable strings, including abstention
  or unsupported mapping where relevant. No invented supported MIME/client claims.

The raw input is immutable. Preserve legitimate current-body content. Matching
budgets must bound adversarial regex/input/part counts, nesting and wall time.
HTML transformations, MIME decoding and normalization must not be presented as
exact raw-source positions without a proven mapping ledger. Fail closed.

The visible contract is deliberately small. Hidden tests and independent real-Gold
scoring remain evaluator-only. No fixed precision/F1 threshold is guaranteed by
these starter examples, and a synthetic fixture is never real-mail accuracy.

## Reserved optional classifier-mode interface

The **only executable parser mode is `ml_mode="off"`**, which uses deterministic rules, dictionaries, MIME handling and BoundaryReviewer. Calling an API with the mode omitted and with `ml_mode="off"` MUST yield exactly the same result, including `authorized_removals=[]`. Neither variant may load weights, perform ML inference or network calls. The future `ml_mode="recover"` is *recognized but unimplemented*: reject it clearly with a stable `NotImplementedError` identifying `ml_mode=recover`, without processing input or writing output. Unsupported modes (including `on`) are a `ValueError`, never a silent fallback. This is a reserved extension point only: no trained classifier or ML score is part of Phase 4.

At the API boundary, `recover` raises `NotImplementedError` with the message
`ml_mode=recover is not implemented` before modifying input or invoking any
model. Include `melusense/processors/recovery_hook.py` only as an explicit
unsupported extension interface: no weights, logits, optimizer, dataset loader,
threshold learner or remote call. Default and explicit `off` must return
identical results; `recover` is never scored as implemented detection.

The locally executable entry point must be `python -m melusense <local-input.eml-or-text> --ml-mode off [--output result.json]`. `--ml-mode recover` must exit nonzero with an explicit unsupported message, without writing a result. File output must never overwrite an existing path and must use restricted permissions because messages may contain private text. No hidden/reference data or external model calls. Use the required source modules in [AGENTS.md](../AGENTS.md#required-candidate-source-layout) and verify with the same frozen tests for all models.

Use standard-library `argparse` for the CLI and local files only;
`melusense/__main__.py` dispatches to `cli.main()`. Do not add a dependency just
for the CLI.
