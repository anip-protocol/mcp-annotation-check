"""Secret redaction for every error text that reaches a report or the console.

`redact` replaces, with `[REDACTED]`:
  - every given secret, verbatim, wherever it appears;
  - the value of any `Authorization` header (`Authorization: …`, `'authorization': '…'`),
    up to the closing quote or the end of the line;
  - the value after `Bearer`;
  - the value after `token=` / `token:` (including `access_token=`), and after `token `
    when that value looks like a credential (it contains a digit, `_` or `-`), so that
    ordinary sentences such as "the token is invalid" stay readable;
  - anything shaped like a GitHub token (`ghp_`, `gho_`, `ghu_`, `ghs_`, `ghr_`,
    `github_pat_`).

The patterns mean a traceback that prints request headers is safe even when the
secret list is empty. `redact` never raises: if redaction itself fails, the text
cannot be shown to be safe, so a placeholder is returned instead of the input.
"""

import re
from collections.abc import Iterable

REDACTED = "[REDACTED]"

# Each pattern's group 1 (if any) is kept; the rest of the match becomes REDACTED.
_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"""(authorization["']?\s*[:=]\s*["']?)[^"'\r\n]+""", re.IGNORECASE),
    re.compile(r"""\b(bearer\s+)[^\s"',;]+""", re.IGNORECASE),
    re.compile(r"""\b((?:access_)?token["']?\s*[:=]\s*["']?)[^\s"'&,;]+""", re.IGNORECASE),
    re.compile(r"""\b(token\s+)(?=[^\s"',;]*[\d_-])[^\s"',;]+""", re.IGNORECASE),
    re.compile(r"\b()(?:gh[pousr]_[A-Za-z0-9]{16,}|github_pat_[A-Za-z0-9_]{16,})"),
]


def redact(text: str, secrets: Iterable[str] = ()) -> str:
    try:
        out = str(text)
        found = {s for s in secrets if isinstance(s, str) and s}
        for secret in sorted(found, key=len, reverse=True):
            out = out.replace(secret, REDACTED)
        for pattern in _PATTERNS:
            out = pattern.sub(lambda m: m.group(1) + REDACTED, out)
        return out
    except Exception:
        return f"{REDACTED} (error text withheld: redaction failed)"
