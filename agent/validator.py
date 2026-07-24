"""The output-validation layer — OrbitWarden's trust guarantee.

Design principle: numbers never travel through the model. The maneuver card is
*server-composed* (the agent supplies the event + option + prose; the server
fills every figure from the engine). For the model's free-form prose, this layer
extracts every number it writes and verifies it against the set of values that
actually came from tool results in the session. Any number the model invented —
one not traceable to a tool output — is flagged and annotated, never shown as fact.

Every artifact is logged to an audit trail, so the demo's "provably computed"
claim is demonstrable from the record.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

# Numbers we care about verifying: integers and decimals, optional sign/scientific.
_NUMBER_RE = re.compile(r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")

# Unicode dashes the model may emit (non-breaking hyphen, en/em dash, minus sign).
# Normalized to ASCII hyphen-minus so date/time components parse consistently in
# both the truth set and the model's prose — otherwise "2026‑07‑25" (non-breaking
# hyphens) yields +7/+25 while a timestamp "2026-07-25" yields -7/-25.
_DASH_CHARS = "‐‑‒–—−"

# Tiny integers that are almost certainly prose, not physics ("top 3", "2 options").
_TRIVIAL_THRESHOLD = 10

DEFAULT_REL_TOL = 0.02  # 2% — covers rounding the model may do when restating


def _normalize_dashes(text: str) -> str:
    for ch in _DASH_CHARS:
        text = text.replace(ch, "-")
    return text


@dataclass
class Finding:
    value: float
    status: str  # "verified" | "unverified" | "trivial"
    matched: float | None = None


@dataclass
class AuditRecord:
    artifact_type: str  # "prose" | "maneuver_card"
    created_at: datetime
    findings: list[Finding] = field(default_factory=list)
    passed: bool = True


def extract_numbers(text: str) -> list[float]:
    """All numeric values appearing in a string (unicode dashes normalized)."""
    text = _normalize_dashes(text)
    out = []
    for m in _NUMBER_RE.finditer(text):
        try:
            out.append(float(m.group()))
        except ValueError:
            continue
    return out


def build_truth_set(tool_results: list[dict]) -> set[float]:
    """The set of numeric values the agent legitimately received from tools.

    Walks the tool-result dicts recursively so nested values (RSW components,
    option fields, card figures) all become ground truth. Numbers embedded in
    strings (object names like "COSMOS 2251 DEB", ISO timestamps) are also
    extracted, so the model can legitimately reference them without being flagged.
    """
    truth: set[float] = set()

    def walk(node) -> None:
        if isinstance(node, dict):
            for v in node.values():
                walk(v)
        elif isinstance(node, (list, tuple)):
            for v in node:
                walk(v)
        elif isinstance(node, bool):
            return  # bools are not physics numbers
        elif isinstance(node, (int, float)):
            truth.add(float(node))
        elif isinstance(node, str):
            for num in extract_numbers(node):
                truth.add(num)

    for result in tool_results:
        walk(result)
    return truth


def _matches(value: float, truth: set[float], rel_tol: float) -> float | None:
    """Return the matching truth value if `value` is within tolerance, else None."""
    for t in truth:
        if t == 0.0:
            if abs(value) <= rel_tol:
                return t
        elif abs(value - t) <= rel_tol * max(abs(t), 1e-9):
            return t
    return None


def validate_text(
    text: str,
    truth: set[float],
    rel_tol: float = DEFAULT_REL_TOL,
) -> tuple[str, list[Finding]]:
    """Verify every number in `text` against the truth set.

    Returns (annotated_text, findings). Unverified non-trivial numbers are
    annotated inline with a warning marker so the operator sees they are not
    traceable to the engine.
    """
    findings: list[Finding] = []
    text = _normalize_dashes(text)

    def replace(match: re.Match) -> str:
        raw = match.group()
        try:
            value = float(raw)
        except ValueError:
            return raw
        if abs(value) < _TRIVIAL_THRESHOLD and value == int(value):
            findings.append(Finding(value, "trivial"))
            return raw
        matched = _matches(value, truth, rel_tol)
        if matched is not None:
            findings.append(Finding(value, "verified", matched))
            return raw
        findings.append(Finding(value, "unverified"))
        return f"{raw} ⚠[unverified]"

    annotated = _NUMBER_RE.sub(replace, text)
    return annotated, findings


class Validator:
    """Session-scoped validator with an audit trail."""

    def __init__(self, rel_tol: float = DEFAULT_REL_TOL):
        self.rel_tol = rel_tol
        self.truth: set[float] = set()
        self.audit: list[AuditRecord] = []

    def observe(self, tool_results: list[dict]) -> None:
        """Add tool outputs to the ground-truth set."""
        self.truth |= build_truth_set(tool_results)

    def observe_arguments(self, args: dict) -> None:
        """Add a tool call's arguments to the truth set. The model generated these
        values (e.g. a constraint it chose), so restating them is legitimate."""
        self.truth |= build_truth_set([args])

    def observe_text(self, text: str) -> None:
        """Add numbers from free text (e.g. the operator's stated constraints) to
        the truth set, so restating them is not flagged as invented."""
        for num in extract_numbers(text):
            self.truth.add(num)

    def validate_prose(self, text: str) -> str:
        """Validate model prose; annotate unverified numbers; log the artifact."""
        annotated, findings = validate_text(text, self.truth, self.rel_tol)
        unverified = [f for f in findings if f.status == "unverified"]
        self.audit.append(
            AuditRecord(
                artifact_type="prose",
                created_at=datetime.now(timezone.utc),
                findings=findings,
                passed=not unverified,
            )
        )
        return annotated

    def validate_card(self, card: dict) -> AuditRecord:
        """A server-composed card is trusted by construction; log it for the trail."""
        record = AuditRecord(
            artifact_type="maneuver_card",
            created_at=datetime.now(timezone.utc),
            findings=[],
            passed=True,
        )
        self.audit.append(record)
        return record

    @property
    def all_passed(self) -> bool:
        return all(r.passed for r in self.audit)
