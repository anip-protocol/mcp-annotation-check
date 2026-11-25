"""Secret redaction for every error text that reaches a report or the console.

Stub: returns its input unchanged. Task 7 completes it.
"""

from collections.abc import Iterable


def redact(text: str, secrets: Iterable[str] = ()) -> str:
    return text
