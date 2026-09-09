"""Boundary between the Markdown workflow and where documents are stored.

Version values are opaque JSON-serializable tokens, never incremented by Worker.
Only a definitive conditional conflict may raise Conflict. Other write failures
are potentially committed and therefore block the target pending investigation.
"""
from typing import Protocol


class WikiStorage(Protocol):
    def list_markdown(self) -> list[str]:
        """List logical relative Markdown paths, without changing their contents."""
        ...

    def read(self, target: str) -> dict | None:
        """Return content bytes, item and version from ONE stable version.

        None means confirmed absence; permission/network errors must propagate.
        """
        ...

    def write(self, target: str, content: bytes, expected: list | None) -> dict:
        """Write exact bytes if [item, version] matches; None means create-only.

        Return a durable receipt with receipt, target, item, version and hash.
        """
        ...

    def verify(self, result: dict) -> bool:
        """Verify independent operation evidence, not merely current content hash."""
        ...

    def receipt(self, receipt: str, prepared: dict) -> dict | None:
        """Find evidence for this specific prepared conditional operation."""
        ...
