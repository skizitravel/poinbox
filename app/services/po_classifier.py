"""PO classification logic.

An email/attachment is classified as a likely Purchase Order when:
  1. The attachment extension is one of: .pdf, .xlsx, .xls
  AND
  2. Either the subject or the attachment filename contains at least one of
     these keywords (case-insensitive, whole-word match):
       PO, PURCHASE ORDER, REV, ORDER

Text is normalised (upper-cased, trimmed, underscores/dashes treated as word
separators) before matching so that filenames like ``PO_1234_acme.pdf`` are
correctly identified while words like ``REPORT`` or ``SUPPORT`` are not.
"""

import os
import re
from typing import List

# Keywords that indicate a purchase order (upper-case; checked with word boundaries)
PO_KEYWORDS: List[str] = ["PURCHASE ORDER", "PO", "REV", "ORDER"]

# Allowed attachment extensions (lower-case)
PO_EXTENSIONS: List[str] = [".pdf", ".xlsx", ".xls"]

# Pre-compile one regex pattern per keyword using word boundaries so that
# "PO" does not accidentally match inside "REPORT" or "SUPPORT".
_KEYWORD_PATTERNS: List[re.Pattern] = [
    re.compile(r"\b" + re.escape(kw) + r"\b")
    for kw in PO_KEYWORDS
]


def _normalise(text: str) -> str:
    """Upper-case, replace underscores/dashes with spaces, then collapse whitespace."""
    text = text.upper().strip()
    text = re.sub(r"[_\-]", " ", text)
    return re.sub(r"\s+", " ", text)


def is_likely_po(subject: str, attachment_name: str) -> bool:
    """Return True if the email is likely a purchase order.

    Args:
        subject: The email subject line.
        attachment_name: The filename of the attachment.

    Returns:
        True if the message matches PO extension AND keyword rules.
    """
    ext = os.path.splitext(attachment_name.lower())[1]
    if ext not in PO_EXTENSIONS:
        return False

    norm_subject = _normalise(subject)
    norm_filename = _normalise(attachment_name)

    for pattern in _KEYWORD_PATTERNS:
        if pattern.search(norm_subject) or pattern.search(norm_filename):
            return True

    return False
