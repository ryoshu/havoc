"""Observable decision provenance for the GIA execution boundary.

Provenance records describe the request context that authorized a committed
mutation.  They are deliberately not model-reasoning traces: alternatives
mean capabilities advertised by the server but not selected, and any supplied
model text is labelled untrusted metadata.
"""

from .models import DecisionProvenance, DecisionRecord, PROVENANCE_VERSION
from .redaction import REDACTED, capability_set_digest, redact_sensitive

__all__ = [
    "DecisionProvenance",
    "DecisionRecord",
    "PROVENANCE_VERSION",
    "REDACTED",
    "capability_set_digest",
    "redact_sensitive",
]
