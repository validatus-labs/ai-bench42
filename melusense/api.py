"""Candidate entrypoints. Implement independently according to docs/contract.md."""


def detect_text(text: str, locale: str = "auto") -> dict:
    raise NotImplementedError("Implement the text pipeline in this trial")


def detect_eml(raw: bytes, locale: str = "auto") -> dict:
    raise NotImplementedError("Implement the MIME pipeline in this trial")
