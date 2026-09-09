from __future__ import annotations

import contextlib
import difflib
import fcntl
import json
import re
import sqlite3
from pathlib import Path

from .common import LIMIT, MARKER, Invalid, Conflict, digest, now, parse, target_path, read_file
from .fixture import FixtureRemote  # compatibility for existing clients
from .storage import WikiStorage
from . import context as proposal_context


def bundle(folder):
    folder = Path(folder)
    raw = read_file(folder / 'proposal.ready.json')
    m = parse(raw)
    if not isinstance(m, dict):
        raise Invalid('manifest must be an object')
    proposed = read_file(folder / 'proposed.md')
    base = read_file(folder / 'base.md') if (folder / 'base.md').exists() else None
    return validate_bundle(raw, base, proposed)


def _table_value(value):
    return value.replace('\\|', '|').replace('<br>', '\n').replace('\\\\', '\\')


def _contribution_references(worker, text):
    scope_match = re.search(
        r'\n## Scope and impact files\n\n\| File \| Version \| Impact \|\n'
        r'\| --- \| --- \| --- \|\n(.*?)\n\n## Sources\n\n'
        r'\| File \| Version \|\n\| --- \| --- \|\n(.*?)\Z', text, re.S)
    if not scope_match:
        raise Invalid('missing scope/impact or sources table')
    scope = []
    for line in scope_match.group(1).splitlines():
        match = re.fullmatch(r'\| ([^|]+) \| (\d{8}-\d+) \| ((?:\\\||[^|])+) \|', line)
        if not match or not match[3].strip():
            raise Invalid('invalid scope/impact file row')
        path = match[1].strip()
        ref = proposal_context.reference(worker, path, match[2])
        scope.append(dict(path=path, version=match[2], impact=_table_value(match[3].strip()), ref=ref))
    if not scope or len({item['path'] for item in scope}) != len(scope):
        raise Invalid('scope must contain unique versioned files, primary target first')
    sources = []
    for line in scope_match.group(2).splitlines():
        if not line.strip():
            continue
        match = re.fullmatch(r'\| ([^|]+) \| (\d{8}-\d+) \|', line)
        if not match:
            raise Invalid('invalid source file row')
        path = match[1].strip()
        sources.append(proposal_context.reference(worker, path, match[2]))
    if len({item['path'] for item in sources}) != len(sources):
        raise Invalid('sources must contain unique versioned files')
    return scope, sources


def contribution_file(raw, worker=None):
    """Decode a readable Markdown contribution into the existing frozen bundle."""
    if not isinstance(raw, bytes) or len(raw) > 4 * LIMIT + 65536:
        raise Invalid('contribution file exceeds size limit')
    try:
        text = raw.decode('utf-8')
    except UnicodeError as exc:
        raise Invalid('contribution file must be UTF-8 Markdown') from exc
    if not text.startswith('# Wiki contribution\n\n| Field | Value |\n| --- | --- |\n'):
        raise Invalid('invalid Markdown contribution header')
    metadata = {}
    metadata_text = text.split('\n\n## ', 1)[0]
    for key, value in re.findall(r'^\| ([A-Za-z][A-Za-z0-9 _-]*) \| (.*?) \|$', metadata_text, re.M):
        if key in metadata:
            raise Invalid(f'duplicate contribution field: {key}')
        metadata[key] = _table_value(value)
    required = {'Format', 'Boundary', 'ID', 'Base SHA-256', 'Proposed SHA-256', 'Author', 'Reason'}
    if not required <= metadata.keys():
        raise Invalid('incomplete Markdown contribution table')
    if metadata['Format'] != 'wiki-contribution-v3':
        raise Invalid('unsupported contribution format; expected wiki-contribution-v3')
    boundary = metadata['Boundary']
    if not re.fullmatch(r'wc-[a-z0-9-]{1,200}', boundary):
        raise Invalid('invalid contribution boundary')
    start = f'\n\n## Proposed content\n\n--- {boundary}:proposed ---\n\n'
    middle = f'\n\n--- {boundary}:base ---\n\n## Base content\n\n'
    end = f'\n\n--- {boundary}:end ---\n'
    if any(text.count(marker) != 1 for marker in (start, middle, end)) or not text.endswith(end):
        raise Invalid('missing or ambiguous contribution breaks')
    text, payload = text.split(start)
    if middle not in payload[:-len(end)]:
        raise Invalid('contribution breaks are out of order')
    proposed_text, base_text = payload[:-len(end)].split(middle)
    if boundary in proposed_text or boundary in base_text:
        raise Invalid('contribution boundary occurs in content')
    base, proposed = base_text.encode('utf-8'), proposed_text.encode('utf-8')
    if worker is None:
        raise Invalid('worker state required for version-only contribution')
    scope_impact, source_references = _contribution_references(worker, text)
    target_ref = scope_impact[0]['ref']
    by_path = {}
    for ref in [item['ref'] for item in scope_impact[1:]] + source_references:
        old = by_path.get(ref['path'])
        if old is not None and old != ref:
            raise Invalid('a file cannot use different versions in scope and sources')
        by_path[ref['path']] = ref
    if target_ref['path'] in by_path and by_path[target_ref['path']] != target_ref:
        raise Invalid('target must use one version across scope and sources')
    by_path.pop(target_ref['path'], None)
    base_hash = metadata['Base SHA-256']
    if target_ref['hash'] != base_hash:
        raise Invalid('primary scope file must match the base content')
    manifest = dict(schema_version=1, id=metadata['ID'], target=target_ref['path'],
                    base_hash=base_hash, proposed_hash=metadata['Proposed SHA-256'],
                    reason=metadata['Reason'], sources=[],
                    context=dict(target=target_ref, sources=list(by_path.values())),
                    scope_impact=[{k: item[k] for k in ('path', 'version', 'impact')} for item in scope_impact],
                    source_references=[{k: ref[k] for k in ('path', 'version')} for ref in source_references])
    author_metadata = {key: metadata[label] for key, label in
                       [('name', 'Author name'), ('role', 'Author role'),
                        ('expert', 'Author expert'), ('metadata_source', 'Author metadata source')]
                       if label in metadata}
    if author_metadata:
        manifest['author_metadata'] = author_metadata
    raw_manifest = json.dumps(manifest, ensure_ascii=False).encode()
    return metadata['Author'], validate_bundle(raw_manifest, base, proposed)


def validate_bundle(raw, base, proposed):
    if any(not isinstance(data, bytes) or len(data) > LIMIT for data in (raw, proposed)) or (
            base is not None and (not isinstance(base, bytes) or len(base) > LIMIT)):
        raise Invalid('bundle files must be bytes within the size limit')
    m = parse(raw)
    required = {'schema_version', 'id', 'target', 'base_hash', 'proposed_hash', 'reason'}
    if not isinstance(m, dict) or not required <= m.keys() or m.keys() - required - {
            'sources', 'knowledge_change', 'context', 'scope_impact', 'source_references', 'author_metadata'}:
        raise Invalid('manifest has missing or unknown fields')
    if type(m['schema_version']) is not int or m['schema_version'] != 1:
        raise Invalid('unsupported schema version')
    if not isinstance(m['id'], str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}', m['id']):
        raise Invalid('invalid proposal ID')
    target_path(m['target'])
    if not isinstance(m['reason'], str) or not m['reason'].strip():
        raise Invalid('reason required')
    if 'sources' in m and (not isinstance(m['sources'], list) or
                           any(not isinstance(s, str) for s in m['sources'])):
        raise Invalid('sources must be strings')
    if 'scope_impact' in m and (not isinstance(m['scope_impact'], list) or any(
            not isinstance(item, dict) or set(item) != {'path', 'version', 'impact'} or
            any(not isinstance(item[key], str) or not item[key].strip() for key in item)
            for item in m['scope_impact'])):
        raise Invalid('scope_impact must contain file, version and impact')
    if 'source_references' in m and (not isinstance(m['source_references'], list) or any(
            not isinstance(item, dict) or set(item) != {'path', 'version'} or
            any(not isinstance(item[key], str) or not item[key].strip() for key in item)
            for item in m['source_references'])):
        raise Invalid('source_references must contain file and version')
    if 'knowledge_change' in m:
        from .knowledge import validate_change
        validate_change(m['knowledge_change'], base, proposed)
    if 'author_metadata' in m:
        metadata = m['author_metadata']
        if (not isinstance(metadata, dict) or metadata.keys() - {'name', 'role', 'expert', 'metadata_source'}
                or any(not isinstance(v, str) or not v.strip() for v in metadata.values())):
            raise Invalid('invalid author metadata')
    for key in ('base_hash', 'proposed_hash'):
        if key == 'base_hash' and m[key] is None:
            continue
        if not isinstance(m[key], str) or not re.fullmatch('[a-f0-9]{64}', m[key]):
            raise Invalid(f'invalid {key}')
    if (m['base_hash'] is None) != (base is None):
        raise Invalid('base content must match create/update mode')
    if digest(proposed) != m['proposed_hash'] or (base is not None and digest(base) != m['base_hash']):
        raise Invalid('payload hash mismatch')
    try:
        content = proposed.decode('utf-8')
        if base is not None:
            base.decode('utf-8')
    except UnicodeError as exc:
        raise Invalid('Markdown must be UTF-8') from exc
    if MARKER in content:
        raise Invalid('proposed content contains reserved review marker')
    return m, raw, base, proposed


class Worker:
    def __init__(self, root, remote: WikiStorage, reviewer, owner='Pilot owner'):
        if not reviewer or any(c in owner + reviewer for c in '\r\n<>'):
            raise Invalid('invalid owner or reviewer')
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.remote, self.reviewer, self.owner = remote, reviewer, owner
        self.db = sqlite3.connect(self.root / 'state.sqlite')
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS proposals(
            id TEXT PRIMARY KEY, target TEXT, bundle_hash TEXT, manifest BLOB,
            base BLOB, proposed BLOB, submitter TEXT, state TEXT,
            artifact BLOB, artifact_hash TEXT, decision TEXT,
            phase TEXT, prepared TEXT, result TEXT, error TEXT);
          CREATE TABLE IF NOT EXISTS history(id TEXT PRIMARY KEY, record TEXT);
          CREATE TABLE IF NOT EXISTS resolutions(
            id TEXT, actor TEXT, time TEXT, outcome TEXT, evidence TEXT);
        ''')

        proposal_context.initialize(self.db)

    @contextlib.contextmanager
    def lock(self):
        with (self.root / 'worker.lock').open('a') as file:
            fcntl.flock(file, fcntl.LOCK_EX)
            yield

    def row(self, ident):
        row = self.db.execute('SELECT * FROM proposals WHERE id=?', (ident,)).fetchone()
        if row is None:
            raise Invalid('unknown proposal')
        return row

    def scan(self, folder, submitter):
        path = Path(folder)
        if path.is_file():
            if path.is_symlink():
                raise Invalid('contribution file must not be a symlink')
            with path.open('rb') as stream:
                _, (_, raw, base, proposed) = contribution_file(stream.read(4 * LIMIT + 65537), self)
            return self.submit(raw, base, proposed, submitter)
        if not path.is_dir() or path.is_symlink():
            raise Invalid('scan path must be a contribution file or directory')
        if (path / 'proposal.ready.json').is_file():
            _, raw, base, proposed = bundle(folder)
            return self.submit(raw, base, proposed, submitter)
        files = sorted(path.glob('*.contribution.md'))
        if not files:
            raise Invalid('contribution directory contains no .contribution.md files')
        return [self.scan(file, submitter) for file in files]

    def import_contribution(self, raw, submitter):
        _, (_, manifest, base, proposed) = contribution_file(raw, self)
        return self.submit(manifest, base, proposed, submitter)

    def submit(self, manifest: bytes, base: bytes | None, proposed: bytes, submitter: str):
        """Ingest bytes from any adapter; identity must come from its trusted boundary."""
        if not submitter:
            raise Invalid('trusted submitter identity required')
        with self.lock():
            m, raw, base, proposed = validate_bundle(manifest, base, proposed)
            if 'context' in m:
                proposal_context.validate(self, m['context'], m['target'], base)
            old = self.db.execute('SELECT * FROM proposals WHERE id=?', (m['id'],)).fetchone()
            if old:
                if old['bundle_hash'] != digest(raw) or old['submitter'] != submitter:
                    raise Invalid('proposal ID already bound to another bundle or identity')
                return m['id']
            if 'context' in m and proposal_context.freshness(self, m['context'])['status'] != 'current':
                raise Conflict('proposal context is stale; read new context and reassess')
            with self.db:
                self.db.execute('''INSERT INTO proposals
                  (id,target,bundle_hash,manifest,base,proposed,submitter,state)
                  VALUES(?,?,?,?,?,?,?,'pending')''',
                  (m['id'], m['target'], digest(raw), raw, base, proposed, submitter))
            return m['id']

    def propose(self, ident, target, proposed, submitter, reason, sources=None):
        """Capture a base from the configured Markdown storage and submit a change."""
        target_path(target)
        current = self.remote.read(target)
        base = None if current is None else current['content']
        manifest = dict(schema_version=1, id=ident, target=target,
                        base_hash=None if base is None else digest(base),
                        proposed_hash=digest(proposed), reason=reason, sources=sources or [])
        return self.submit(json.dumps(manifest).encode(), base, proposed, submitter)

    def agent_context(self, target, sources):
        with self.lock():
            return proposal_context.capture(self, target, sources)

    def document_history(self, path, version=None):
        with self.lock():
            target_path(path)
            if version is not None:
                ref = proposal_context.reference(self, path, version)
                return proposal_context.snapshot(self, ref)
            changes = []
            for row in self.db.execute('SELECT id FROM proposals WHERE target=? ORDER BY rowid', (path,)):
                proposal = self.row(row['id'])
                self.integrity(proposal)
                manifest = parse(proposal['manifest'])
                history = self.db.execute('SELECT record FROM history WHERE id=?', (row['id'],)).fetchone()
                changes.append(dict(id=row['id'], state=proposal['state'], submitter=proposal['submitter'],
                    author_metadata=manifest.get('author_metadata', {}), reason=manifest['reason'],
                    base_hash=manifest['base_hash'], proposed_hash=manifest['proposed_hash'],
                    artifact_hash=proposal['artifact_hash'],
                    decision=parse(proposal['decision']) if proposal['decision'] else None,
                    resolutions=[dict(item) for item in self.db.execute(
                        'SELECT actor,time,outcome,evidence FROM resolutions WHERE id=? ORDER BY rowid', (row['id'],))],
                    publication=parse(history['record']) if history else None,
                    diff=''.join(difflib.unified_diff((proposal['base'] or b'').decode().splitlines(True),
                        proposal['proposed'].decode().splitlines(True), fromfile='base', tofile='proposed'))))
            return dict(path=path, versions=proposal_context.versions(self, path), changes=changes)

    def agent_propose(self, data):
        required = ('id', 'target', 'content', 'submitter', 'reason')
        if any(not isinstance(data.get(k), str) or not data[k].strip() for k in required) or 'context' not in data:
            raise Invalid('agent proposal requires id, target, content, submitter, reason and context')
        # Use the context the agent read, never silently recapture the current base.
        with self.lock():
            context = data['context']
            if not isinstance(context, dict) or 'target' not in context:
                raise Invalid('invalid agent context')
            original = proposal_context.snapshot(self, context['target'])
            base = None if original['content'] is None else original['content'].encode()
            proposal_context.validate(self, context, data['target'], base)
        proposed = data['content'].encode()
        manifest = dict(schema_version=1, id=data['id'], target=data['target'],
                        base_hash=None if base is None else digest(base), proposed_hash=digest(proposed),
                        reason=data['reason'], sources=data.get('sources', []), context=context)
        if 'knowledge_change' in data:
            manifest['knowledge_change'] = data['knowledge_change']
        return self.submit(json.dumps(manifest, ensure_ascii=False).encode(), base, proposed, data['submitter'])

    def integrity(self, row):
        m = parse(row['manifest'])
        if (digest(row['manifest']) != row['bundle_hash'] or
            digest(row['proposed']) != m['proposed_hash'] or
            (None if row['base'] is None else digest(row['base'])) != m['base_hash'] or
            m['id'] != row['id'] or m['target'] != row['target']):
            raise Invalid('frozen bundle changed')
        if 'context' in m:
            proposal_context.validate(self, m['context'], m['target'], row['base'])
        if row['decision']:
            decision = parse(row['decision'])
            if (row['artifact'] is None or digest(row['artifact']) != row['artifact_hash'] or
                decision['artifact_hash'] != row['artifact_hash'] or
                decision['bundle_hash'] != row['bundle_hash']):
                raise Invalid('approved artifact changed')

    def _artifact(self, row, actor, stamp):
        return (f'{MARKER} start -->\n'
                f'> Phiên bản đã được review · Owner: {self.owner}\n'
                f'> Proposal: {row["id"]} · Reviewer: {actor} · {stamp}\n'
                '> Review does not guarantee absolute correctness.\n'
                f'{MARKER} end -->\n\n').encode() + row['proposed']

    def preview(self, ident, actor):
        with self.lock():
            row = self.row(ident)
            self.integrity(row)
            self.check_reviewer(row, actor)
            if row['state'] != 'pending':
                raise Invalid('proposal is not pending')
            stamp = now()
            artifact = self._artifact(row, actor, stamp)
            m = parse(row['manifest'])
            diff = ''.join(difflib.unified_diff(
                (row['base'] or b'').decode().splitlines(True),
                artifact.decode().splitlines(True), fromfile='base.md', tofile='artifact.md'))
            return dict(bundle_hash=row['bundle_hash'], artifact=artifact, time=stamp,
                        diff=diff, reason=m['reason'], sources=m.get('sources', []),
                        scope_impact=m.get('scope_impact', []),
                        source_references=m.get('source_references', []),
                        knowledge_change=m.get('knowledge_change'), context=m.get('context'),
                        context_documents=proposal_context.documents(self, m.get('context')),
                        context_status=proposal_context.freshness(self, m.get('context')))

    def check_reviewer(self, row, actor):
        if actor != self.reviewer:
            raise Invalid('actor is not the configured reviewer')
        if actor == row['submitter']:
            raise Invalid('self-review is forbidden')

    def review(self, ident, actor, preview, approve, reason):
        with self.lock():
            row = self.row(ident)
            self.integrity(row)
            self.check_reviewer(row, actor)
            if row['state'] != 'pending' or preview['bundle_hash'] != row['bundle_hash']:
                raise Invalid('review is no longer current')
            if not reason.strip():
                raise Invalid('decision reason required')
            artifact = self._artifact(row, actor, preview['time'])
            if artifact != preview['artifact']:
                raise Invalid('review artifact does not match the server preview')
            context = parse(row['manifest']).get('context')
            if approve and context is not None and proposal_context.freshness(self, context)['status'] != 'current':
                raise Conflict('proposal context is stale; read new context and reassess')
            decision = dict(actor=actor, time=preview['time'], reason=reason, approved=approve,
                            bundle_hash=row['bundle_hash'], artifact_hash=digest(artifact))
            with self.db:
                self.db.execute('''UPDATE proposals SET state=?,artifact=?,artifact_hash=?,decision=?
                  WHERE id=?''', ('approved' if approve else 'rejected', artifact,
                                  digest(artifact), json.dumps(decision), ident))

    def finish(self, ident):
        row = self.row(ident)
        self.integrity(row)
        # Register the verified artifact, not a later remote read (also on recovery).
        published_version = proposal_context.record(self, row['target'], row['artifact'])
        record = dict(id=ident, target=row['target'], submitter=row['submitter'],
                      bundle_hash=row['bundle_hash'], base_hash=parse(row['manifest'])['base_hash'],
                      proposed_hash=digest(row['proposed']), artifact_hash=row['artifact_hash'],
                      decision=parse(row['decision']), prepared=parse(row['prepared']),
                      result=parse(row['result']), context=parse(row['manifest']).get('context'),
                      published_version=published_version)
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO history VALUES(?,?)', (ident, json.dumps(record)))
            self.db.execute("UPDATE proposals SET state='published',phase='done',error=NULL WHERE id=?", (ident,))

    def publish(self, ident):
        with self.lock():
            row = self.row(ident)
            self.integrity(row)
            if row['state'] == 'published':
                return 'published'
            if row['state'] != 'approved':
                raise Invalid('proposal is not approved')
            if row['phase'] == 'written':
                self.finish(ident)
                return 'published'
            blocked = self.db.execute("SELECT id FROM proposals WHERE target=? AND phase='writing'",
                                      (row['target'],)).fetchone()
            if blocked:
                raise Invalid(f'target blocked by uncertain write: {blocked[0]}')
            context = parse(row['manifest']).get('context')
            if context is not None and proposal_context.freshness(self, context)['status'] != 'current':
                with self.db:
                    self.db.execute("UPDATE proposals SET state='stale',error='proposal context changed; new proposal required' WHERE id=?", (ident,))
                return 'stale'
            current = self.remote.read(row['target'])
            base_hash = parse(row['manifest'])['base_hash']
            if (None if current is None else digest(current['content'])) != base_hash:
                with self.db:
                    self.db.execute("UPDATE proposals SET state='stale' WHERE id=?", (ident,))
                return 'stale'
            condition = None if current is None else [current['item'], current['version']]
            if current is not None:
                proposal_context.record(self, row['target'], current['content'])
            prepared = dict(target=row['target'], artifact_hash=row['artifact_hash'],
                            condition=condition, time=now())
            with self.db:
                self.db.execute("UPDATE proposals SET phase='writing',prepared=?,error=NULL WHERE id=?",
                                (json.dumps(prepared), ident))
            try:
                result = self.remote.write(row['target'], row['artifact'], condition)
            except Conflict:
                with self.db:
                    self.db.execute("UPDATE proposals SET state='stale',phase=NULL WHERE id=?", (ident,))
                return 'stale'
            except Exception:
                with self.db:
                    self.db.execute("UPDATE proposals SET error='write outcome unknown; manual evidence required' WHERE id=?", (ident,))
                raise Invalid('write outcome unknown; target blocked') from None
            if result['hash'] != row['artifact_hash'] or result['target'] != row['target'] or not self.remote.verify(result):
                raise Invalid('write result could not be verified; target blocked')
            with self.db:
                self.db.execute("UPDATE proposals SET phase='written',result=? WHERE id=?",
                                (json.dumps(result), ident))
            self.finish(ident)
            return 'published'

    def resolve(self, ident, actor, outcome, evidence, receipt=None):
        with self.lock():
            row = self.row(ident)
            self.integrity(row)
            if actor != self.reviewer or row['phase'] != 'writing' or not evidence.strip():
                raise Invalid('configured reviewer, uncertain write and evidence required')
            if outcome not in ('written', 'not-written'):
                raise Invalid('invalid resolution')
            result = None
            if outcome == 'written':
                result = self.remote.receipt(receipt, parse(row['prepared']))
                if (result is None or result['target'] != row['target'] or
                        result['hash'] != row['artifact_hash'] or not self.remote.verify(result)):
                    raise Invalid('operation receipt does not match prepared write; matching content is insufficient')
            with self.db:
                self.db.execute('INSERT INTO resolutions VALUES(?,?,?,?,?)', (ident, actor, now(), outcome, evidence))
                self.db.execute('UPDATE proposals SET phase=?,result=?,error=NULL WHERE id=?',
                                ('written' if result else None, json.dumps(result) if result else None, ident))
            if result:
                self.finish(ident)

    def status(self):
        return [dict(r) for r in self.db.execute(
            'SELECT id,target,submitter,state,phase,error,bundle_hash,artifact_hash FROM proposals ORDER BY rowid')]

    def detail(self, ident):
        """Return JSON-ready proposal data for trusted review interfaces."""
        with self.lock():
            row = self.row(ident)
            self.integrity(row)
            manifest = parse(row['manifest'])
            return dict(id=row['id'], target=row['target'], submitter=row['submitter'],
                        state=row['state'], phase=row['phase'], error=row['error'],
                        reason=manifest['reason'], sources=manifest.get('sources', []),
                        knowledge_change=manifest.get('knowledge_change'), context=manifest.get('context'),
                        context_documents=proposal_context.documents(self, manifest.get('context')),
                        context_status=proposal_context.freshness(self, manifest.get('context'),
                                                                  include_target=row['state'] != 'published'),
                        base=(row['base'] or b'').decode(), proposed=row['proposed'].decode(),
                        decision=parse(row['decision']) if row['decision'] else None)

    def contribution(self, ident):
        """One consistent read supplies both review context and the exact artifact."""
        with self.lock():
            row = self.row(ident)
            self.integrity(row)
            manifest = parse(row['manifest'])
            stamp = now() if row['state'] == 'pending' else None
            artifact = self._artifact(row, self.reviewer, stamp) if stamp else row['artifact']
            can_review = row['state'] == 'pending' and row['submitter'] != self.reviewer
            return dict(id=row['id'], target=row['target'], submitter=row['submitter'],
                        state=row['state'], phase=row['phase'], error=row['error'],
                        reason=manifest['reason'], sources=manifest.get('sources', []),
                        scope_impact=manifest.get('scope_impact', []),
                        author_metadata=manifest.get('author_metadata', {}),
                        source_references=manifest.get('source_references', []),
                        knowledge_change=manifest.get('knowledge_change'),
                        context_documents=proposal_context.documents(self, manifest.get('context')),
                        context_status=proposal_context.freshness(self, manifest.get('context'), include_target=row['state'] != 'published'),
                        base=(row['base'] or b'').decode(), proposed=row['proposed'].decode(),
                        bundle_hash=row['bundle_hash'], time=stamp, can_review=can_review,
                        artifact=None if artifact is None else artifact.decode(),
                        artifact_hash=None if artifact is None else digest(artifact),
                        diff='' if artifact is None else ''.join(difflib.unified_diff(
                            (row['base'] or b'').decode().splitlines(True), artifact.decode().splitlines(True),
                            fromfile='base.md', tofile='artifact.md')),
                        decision=parse(row['decision']) if row['decision'] else None)

    def backup(self, destination):
        with self.lock():
            destination = Path(destination)
            if destination.exists():
                raise Invalid('backup destination already exists')
            with sqlite3.connect(destination) as target:
                self.db.backup(target)
