"""Deterministic, field-level redaction before audit persistence."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

REDACTED = "[REDACTED]"

# The matcher intentionally errs on the side of removing a value from audit
# storage.  Callers can also pass configured field names for domain-specific
# sensitive data (for example, ``patient_id`` or ``account_number``).
_SENSITIVE_NAME = re.compile(
    r"(?:password|passwd|secret|token|api[_-]?key|authorization|cookie|"
    r"credential|private[_-]?key|access[_-]?key|session[_-]?token|"
    r"client[_-]?secret|ssn|social[_-]?security|credit[_-]?card|"
    r"bearer|encryption[_-]?key)",
    re.IGNORECASE,
)
_SENSITIVE_TEXT = re.compile(
    r"(?:password|passwd|secret|token|api[_-]?key|authorization|cookie|"
    r"credential|private[_-]?key|access[_-]?key|session[_-]?token|"
    r"client[_-]?secret|ssn|social[_-]?security|credit[_-]?card|"
    r"bearer|encryption[_-]?key)\s*[:=]\s*\S+",
    re.IGNORECASE,
)


def _is_sensitive(name: str, configured: set[str]) -> bool:
    normalized = name.strip().lower()
    return normalized in configured or bool(_SENSITIVE_NAME.search(normalized))


def redact_sensitive(
    value: Any,
    *,
    sensitive_fields: Sequence[str] | None = None,
) -> Any:
    """Return a JSON-shaped copy with configured/sensitive fields removed.

    Redaction is recursive and applies to mappings nested in lists.  Mapping
    keys are preserved so an auditor can see that a field was supplied without
    receiving its secret value; scalar values are returned unchanged.
    """

    configured = {
        str(field).strip().lower()
        for field in (sensitive_fields or ())
        if isinstance(field, str) and field.strip()
    }
    if isinstance(value, Mapping):
        return {
            str(key): REDACTED
            if _is_sensitive(str(key), configured)
            else redact_sensitive(item, sensitive_fields=configured)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact_sensitive(item, sensitive_fields=configured) for item in value]
    if isinstance(value, set):
        return sorted(
            redact_sensitive(item, sensitive_fields=configured) for item in value
        )
    if isinstance(value, str) and _SENSITIVE_TEXT.search(value):
        # Free-text rationale/context is explicitly untrusted.  If it
        # contains a credential-like field name, retain no fragment of the
        # potentially embedded secret.
        return REDACTED
    return value


def capability_set_digest(value: Any) -> str:
    """Hash a capability-set snapshot using canonical JSON."""

    def canonicalize(item: Any) -> Any:
        if isinstance(item, Mapping):
            return {
                str(key): canonicalize(value)
                for key, value in sorted(item.items(), key=lambda pair: str(pair[0]))
            }
        if isinstance(item, (list, tuple, set)):
            values = [canonicalize(value) for value in item]
            # Capability/link/template arrays are sets semantically; sorting
            # makes the digest independent of renderer pagination order.
            return sorted(
                values,
                key=lambda value: json.dumps(value, sort_keys=True, default=str),
            )
        return item

    payload = json.dumps(
        canonicalize(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"
