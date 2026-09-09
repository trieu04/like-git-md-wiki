"""Validate author-declared statement edits against the complete document.

No semantic inference is claimed. Authors supply the replacement and scope;
reviewers assess meaning and evidence against the frozen source passage.
"""
import re

from .common import Invalid, MARKER


def body_text(content):
    return re.sub(r'^<!-- wiki-review: start -->.*?<!-- wiki-review: end -->\s*',
                  '', content, count=1, flags=re.S)


def validate_change(change, base, proposed):
    fields = {'before', 'after', 'scope'}
    if not isinstance(change, dict) or set(change) != fields or any(
            not isinstance(change[k], str) for k in fields):
        raise Invalid('knowledge change requires before, after and scope strings')
    before, after = change['before'], change['after']
    if not before.strip() or not after.strip() or not change['scope'].strip() or before == after:
        raise Invalid('provide an original statement, a different replacement and its scope')
    original = body_text((base or b'').decode())
    if original.count(before) != 1:
        raise Invalid('original passage must occur exactly once; select more context')
    if MARKER in after or original.replace(before, after, 1).encode() != proposed:
        raise Invalid('knowledge change does not match the proposed document')
