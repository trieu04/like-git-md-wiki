"""Assisted knowledge changes: lexical discovery and explicit statement edits.

No semantic inference is claimed. Authors supply the replacement and scope;
reviewers assess meaning and evidence against the frozen source passage.
"""
import json
import re
import unicodedata

from .common import Conflict, Invalid, MARKER, digest, target_path


def body_text(content):
    return re.sub(r'^<!-- wiki-review: start -->.*?<!-- wiki-review: end -->\s*',
                  '', content, count=1, flags=re.S)


def tokens(text):
    normalized = unicodedata.normalize('NFD', text.lower()).replace('đ', 'd')
    return set(re.findall(r'[a-z0-9]+', ''.join(c for c in normalized if not unicodedata.combining(c))))


def passages(content):
    section = ''
    for block in re.split(r'\n\s*\n', body_text(content)):
        if not block.strip():
            continue
        heading = re.search(r'^#{1,6}\s+(.+)', block, re.M)
        if heading:
            section = heading.group(1)
        yield section, block


def search(storage, feedback):
    if not isinstance(feedback, str) or not feedback.strip() or len(feedback) > 4000:
        raise Invalid('feedback must contain 1–4000 characters')
    query = tokens(feedback)
    results = []
    for path in storage.list_markdown():
        document = storage.read(path)
        if document is None:
            continue
        for section, passage in passages(document['content'].decode()):
            overlap = query & tokens(passage + ' ' + section + ' ' + path)
            if overlap:
                results.append(dict(target=path, section=section, before=passage,
                                    base_hash=digest(document['content']), score=len(overlap)))
    return sorted(results, key=lambda r: (-r['score'], r['target'], r['before']))[:20]


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


def propose_feedback(worker, data):
    required = ('id', 'target', 'base_hash', 'before', 'after', 'scope', 'feedback', 'submitter')
    if any(not isinstance(data.get(k), str) or not data[k].strip() for k in required):
        raise Invalid('incomplete feedback proposal')
    target_path(data['target'])
    document = worker.remote.read(data['target'])
    if document is None or digest(document['content']) != data['base_hash']:
        raise Conflict('document changed since search; search again before proposing')
    base = document['content']
    change = {k: data[k] for k in ('before', 'after', 'scope')}
    proposed = body_text(base.decode()).replace(change['before'], change['after'], 1).encode()
    validate_change(change, base, proposed)
    manifest = dict(schema_version=1, id=data['id'], target=data['target'],
                    base_hash=digest(base), proposed_hash=digest(proposed),
                    reason=data['feedback'], sources=data.get('sources', []), knowledge_change=change)
    return worker.submit(json.dumps(manifest, ensure_ascii=False).encode(), base, proposed, data['submitter'])
