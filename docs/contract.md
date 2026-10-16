# Candidate API and safety contract

Implement `melusense.detect_text(text: str, locale: str = "auto") -> dict` and
`melusense.detect_eml(raw: bytes, locale: str = "auto") -> dict`.

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
