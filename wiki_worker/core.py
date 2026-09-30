from __future__ import annotations

import contextlib
import difflib
import fcntl
import json
import re
import sqlite3
from pathlib import Path

from .common import LIMIT, MARKER, Invalid, Conflict, digest, now, parse, target_path, read_file
from .fixture import FixtureRemote as FixtureRemote  # public compatibility export
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
    def __init__(self, root, remote: WikiStorage, reviewer, owner='Pilot owner', slack=None):
        if not reviewer or any(c in owner + reviewer for c in '\r\n<>'):
            raise Invalid('invalid owner or reviewer')
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.remote, self.reviewer, self.owner = remote, reviewer, owner
        self.slack = slack
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
          CREATE TABLE IF NOT EXISTS semantic_discussions(
            proposal_id TEXT NOT NULL, sequence INTEGER NOT NULL,
            actor TEXT NOT NULL, time TEXT NOT NULL, action TEXT NOT NULL,
            reason TEXT NOT NULL, resolution_kind TEXT,
            related_contribution_ids TEXT NOT NULL, bundle_hash TEXT NOT NULL,
            PRIMARY KEY(proposal_id, sequence));
          CREATE TABLE IF NOT EXISTS discussions(
            proposal_id TEXT PRIMARY KEY, bundle_hash TEXT NOT NULL,
            status TEXT NOT NULL, version INTEGER NOT NULL,
            created_by TEXT NOT NULL, created_at TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS discussion_events(
            proposal_id TEXT NOT NULL, sequence INTEGER NOT NULL,
            actor TEXT NOT NULL, time TEXT NOT NULL, action TEXT NOT NULL,
            message TEXT NOT NULL, agrees_with INTEGER, decision TEXT,
            bundle_hash TEXT NOT NULL,
            PRIMARY KEY(proposal_id, sequence));
          CREATE TABLE IF NOT EXISTS discussion_topics(
            discussion_id TEXT PRIMARY KEY, project_id TEXT, document_path TEXT NOT NULL,
            section_anchor TEXT NOT NULL, topic_id TEXT NOT NULL, parent_topic_id TEXT,
            proposal_id TEXT, author TEXT NOT NULL, body TEXT NOT NULL, status TEXT NOT NULL,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL, source_refs TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS discussion_comments(
            discussion_id TEXT NOT NULL, comment_id TEXT NOT NULL, parent_comment_id TEXT,
            topic_id TEXT NOT NULL, section_anchor TEXT NOT NULL, proposal_id TEXT,
            author TEXT NOT NULL, body TEXT NOT NULL, status TEXT NOT NULL,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL, source_ref TEXT,
            PRIMARY KEY(discussion_id, comment_id));
          CREATE TABLE IF NOT EXISTS conflict_resolutions(
            proposal_id TEXT PRIMARY KEY, actor TEXT NOT NULL, outcome TEXT NOT NULL,
            base_hash TEXT NOT NULL, current_hash TEXT NOT NULL, replacement_id TEXT,
            reason TEXT NOT NULL, created_at TEXT NOT NULL);
        ''')

        proposal_context.initialize(self.db)
        for column in ('slack_channel', 'slack_thread_ts', 'discord_channel', 'discord_thread_id'):
            try:
                self.db.execute(f'ALTER TABLE discussions ADD COLUMN {column} TEXT')
            except sqlite3.OperationalError:
                pass
        for column in ('slack_channel', 'slack_thread_ts', 'reviewer_notified'):
            try:
                self.db.execute(f'ALTER TABLE discussion_topics ADD COLUMN {column} TEXT')
            except sqlite3.OperationalError:
                pass

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
                    semantic_discussion=self.semantic_discussion(row['id']),
                    discussion=self._workflow_discussion(proposal),
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
                f'> Reviewed version · Owner: {self.owner}\n'
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
                        **self.semantic_discussion(ident),
                        **self._workflow_discussion(row),
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

    @staticmethod
    def _discussion_actor(actor):
        if (not isinstance(actor, str) or not actor.strip() or len(actor.encode()) > 200 or
                any(character in actor for character in '\r\n<>')):
            raise Invalid('valid discussion actor required')
        return actor.strip()

    @staticmethod
    def _discussion_text(value, label):
        if not isinstance(value, str) or not value.strip() or len(value.encode()) > LIMIT:
            raise Invalid(f'{label} required')
        return value

    def _workflow_discussion(self, row):
        """Return the durable, multi-party discussion for this frozen proposal.

        This is deliberately separate from the legacy reviewer-mediated semantic
        log.  Both logs are append-only and both may place an approval hold.
        """
        discussion = self.db.execute('SELECT * FROM discussions WHERE proposal_id=?',
                                     (row['id'],)).fetchone()
        if discussion is None:
            return dict(discussion=None, discussion_history=[],
                        workflow_discussion_version=0, discussion_hold=False)
        if discussion['bundle_hash'] != row['bundle_hash']:
            raise Invalid('discussion is bound to another bundle')
        history = []
        for event in self.db.execute(
                '''SELECT sequence,actor,time,action,message,agrees_with,decision,bundle_hash
                   FROM discussion_events WHERE proposal_id=? ORDER BY sequence''', (row['id'],)):
            if event['bundle_hash'] != row['bundle_hash']:
                raise Invalid('discussion event is bound to another bundle')
            history.append({key: event[key] for key in
                            ('sequence', 'actor', 'time', 'action', 'message', 'agrees_with', 'decision')})
        if len(history) != discussion['version']:
            raise Invalid('discussion history changed')
        status = discussion['status']
        if status not in ('open', 'resolved', 'rejected'):
            raise Invalid('invalid discussion status')
        return dict(
            discussion=dict(proposal_id=row['id'], bundle_hash=discussion['bundle_hash'],
                            status=status, version=discussion['version'],
                            created_by=discussion['created_by'], created_at=discussion['created_at']),
            discussion_history=history, workflow_discussion_version=discussion['version'],
            # A rejection here records the debate outcome; final proposal state
            # still changes only through the existing explicit review action.
            discussion_hold=status != 'resolved')

    def discussion_topics(self, project_id=None, document_path=None, section_anchor=None, topic_id=None):
        """Read the canonical topic/comment store, independent of proposal lifecycle."""
        clauses, args = [], []
        for name, value in (('project_id', project_id), ('document_path', document_path),
                            ('section_anchor', section_anchor), ('topic_id', topic_id)):
            if value is not None:
                clauses.append(name + '=?'); args.append(value)
        where = (' WHERE ' + ' AND '.join(clauses)) if clauses else ''
        topics = [dict(r) for r in self.db.execute('SELECT * FROM discussion_topics' + where + ' ORDER BY created_at', args)]
        for topic in topics:
            topic['source_refs'] = json.loads(topic['source_refs'])
            topic['comments'] = [dict(r) for r in self.db.execute(
                'SELECT * FROM discussion_comments WHERE discussion_id=? ORDER BY created_at', (topic['discussion_id'],))]
        return topics

    def create_topic(self, project_id, document_path, section_anchor, topic_id, author,
                     body, parent_topic_id=None, proposal_id=None, source_refs=None,
                     status='open', discussion_id=None):
        """Create an anchor/topic discussion without requiring a proposal."""
        values = (project_id, document_path, section_anchor, topic_id, author, body)
        if any(not isinstance(v, str) or not v.strip() for v in values):
            raise Invalid('project_id, document_path, section_anchor, topic_id, author and body are required')
        if status not in ('open', 'resolved', 'blocked', 'decision'):
            raise Invalid('invalid topic status')
        discussion_id = discussion_id or digest((project_id + document_path + topic_id + now()).encode())[:24]
        stamp = now()
        thread = None
        if self.slack is not None and hasattr(self.slack, 'open_topic'):
            thread = self.slack.open_topic(discussion_id, document_path, section_anchor, body)
        with self.db:
            self.db.execute('''INSERT INTO discussion_topics
                (discussion_id,project_id,document_path,section_anchor,topic_id,parent_topic_id,proposal_id,author,body,status,created_at,updated_at,source_refs,slack_channel,slack_thread_ts,reviewer_notified)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                            (discussion_id, project_id, document_path, section_anchor, topic_id,
                             parent_topic_id, proposal_id, author, body, status, stamp, stamp,
                             json.dumps(source_refs or []),
                             thread['channel'] if thread else None,
                             thread['thread_ts'] if thread else None, None))
        return discussion_id

    def open_concurrent_discussion(self, proposal_id, actor, section_anchor, reason,
                                   related_proposal_ids=None, project_id='wiki'):
        """Reviewer-only action: open one discussion for a file/section.

        Stale detection never calls this method.  The anchor is the stable
        identity, so proposals for the same file and section share one topic
        and one Slack root thread.
        """
        self.check_reviewer(self.row(proposal_id), actor)
        if not isinstance(section_anchor, str) or not section_anchor.strip() or not isinstance(reason, str) or not reason.strip():
            raise Invalid('section anchor and reason required')
        if related_proposal_ids is not None and not isinstance(related_proposal_ids, list):
            raise Invalid('related proposal IDs must be a list')
        row = self.row(proposal_id)
        ids = list(dict.fromkeys([proposal_id] + list(related_proposal_ids or [])))
        evidence = []
        for related in ids:
            related_row = self.row(related)
            if related_row['target'] != row['target']:
                raise Invalid('all linked contributions must target the discussion document')
            manifest = parse(related_row['manifest'])
            evidence.append(
                f'- `{related}`: base `{manifest["base_hash"] or "new file"}`; '
                f'proposal `{manifest["proposed_hash"]}`; author claim: {manifest["reason"]}')
        body = (f'## What is being discussed\n\n{reason.strip()}\n\n'
                f'**Scope:** `{row["target"]}#{section_anchor}`\n\n'
                '**Related contributions and frozen evidence**\n\n' + '\n'.join(evidence))
        topic = self.db.execute(
            'SELECT * FROM discussion_topics WHERE document_path=? AND section_anchor=? ORDER BY created_at LIMIT 1',
            (row['target'], section_anchor)).fetchone()
        if topic is None:
            discussion_id = 'concurrent-' + digest((row['target'] + '\0' + section_anchor).encode())[:24]
            ident = self.create_topic(project_id, row['target'], section_anchor, discussion_id,
                                      actor, body, proposal_id=proposal_id,
                                      discussion_id=discussion_id)
        else:
            ident = topic['discussion_id']
            self.add_discussion_comment(ident, actor, body, topic['topic_id'],
                                        section_anchor, proposal_id)
        for related in ids:
            exists = self.db.execute(
                'SELECT 1 FROM discussion_comments WHERE discussion_id=? AND proposal_id=?',
                (ident, related)).fetchone()
            if not exists:
                self.add_discussion_comment(ident, actor,
                    f'Linked contribution: `{related}`',
                    self.db.execute('SELECT topic_id FROM discussion_topics WHERE discussion_id=?', (ident,)).fetchone()['topic_id'],
                    section_anchor, related)
        return self.discussion_topics(topic_id=ident)[0]

    def rollback_to_base(self, proposal_id, actor, reason, expected_v2_hash=None):
        """Explicit reviewer rollback of v2 to the frozen v1, conditionally."""
        with self.lock():
            row = self.row(proposal_id)
            self.check_reviewer(row, actor)
            if not isinstance(reason, str) or not reason.strip() or row['base'] is None:
                raise Invalid('reviewer, rollback reason and v1 base required')
            current = self.remote.read(row['target'])
            expected_hash = digest(current['content']) if current else None
            manifest = parse(row['manifest'])
            if current is None or expected_hash == manifest['base_hash']:
                raise Invalid('current file is not v2; rollback refused')
            if expected_v2_hash is not None and expected_hash != expected_v2_hash:
                raise Conflict('current file changed after reviewer evidence; reread before rollback')
            condition = [current['item'], current['version']]
            result = self.remote.write(row['target'], row['base'], condition)
            if result['hash'] != manifest['base_hash'] or not self.remote.verify(result):
                raise Invalid('rollback result could not be verified')
            with self.db:
                self.db.execute('INSERT OR REPLACE INTO conflict_resolutions VALUES(?,?,?,?,?,?,?,?)',
                                (proposal_id, actor, 'rollback', manifest['base_hash'], expected_hash,
                                 None, reason, now()))
                self.db.execute('INSERT INTO resolutions VALUES(?,?,?,?,?)',
                                (proposal_id, actor, now(), 'rollback', reason))
            return dict(proposal_id=proposal_id, outcome='rollback', base_hash=manifest['base_hash'],
                        rolled_back_from=expected_hash, receipt=result.get('receipt'), time=now())

    def _ensure_conflict_discussion(self, row, conflict):
        """Open one durable file discussion for an observed v1→v2 conflict.

        Conflict detection is read-driven (status/detail/contribution), so the
        topic must be idempotent.  The stable discussion ID prevents repeated
        reads from creating another local topic or Slack thread.
        """
        if row['state'] not in ('pending', 'approved'):
            return
        discussion_id = f'conflict-{row["id"]}'
        existing = self.db.execute(
            'SELECT discussion_id FROM discussion_topics WHERE discussion_id=?',
            (discussion_id,)).fetchone()
        if existing is not None:
            return
        current_id = conflict.get('current_contribution_id') or 'external edit'
        body = (f'Concurrent edit detected for proposal `{row["id"]}` on `{row["target"]}`.\n'
                f'Base v1: `{conflict["base_hash"]}`\n'
                f'Current v2: `{conflict["current_hash"]}` ({current_id})\n'
                'Resolve with keep_current, use_incoming, or merge; never overwrite v2 silently.')
        self.create_topic('wiki', row['target'], 'conflict', f'conflict-{row["id"]}',
                          'worker', body, proposal_id=row['id'],
                          discussion_id=discussion_id)

    def close_topic(self, discussion_id, actor, outcome, reason, reviewer=None):
        """Explicitly close a Slack/file discussion and notify the reviewer once.

        Silence is never treated as completion.  A participant or automation
        must send an explicit close action; the reviewer then decides in the
        normal review workflow.
        """
        if outcome not in ('resolved', 'rejected', 'on_hold'):
            raise Invalid('invalid discussion outcome')
        actor = self._discussion_actor(actor); reason = self._discussion_text(reason, 'discussion close reason')
        with self.lock():
            topic = self.db.execute('SELECT * FROM discussion_topics WHERE discussion_id=?', (discussion_id,)).fetchone()
            if topic is None:
                raise Invalid('unknown discussion')
            if topic['status'] in ('resolved', 'decision'):
                raise Invalid('discussion is already closed')
            with self.db:
                self.db.execute('UPDATE discussion_topics SET status=?,updated_at=? WHERE discussion_id=?',
                                ('resolved' if outcome == 'resolved' else ('blocked' if outcome == 'on_hold' else 'decision'), now(), discussion_id))
            if self.slack is not None and topic['slack_thread_ts']:
                thread = {'channel': topic['slack_channel'], 'thread_ts': topic['slack_thread_ts']}
                self.slack.close_topic(thread, discussion_id, outcome, reason, reviewer)
                if not topic['reviewer_notified'] and outcome == 'resolved':
                    self.slack.notify_reviewer(thread, discussion_id, reviewer)
                    with self.db:
                        self.db.execute('UPDATE discussion_topics SET reviewer_notified=? WHERE discussion_id=?', (now(), discussion_id))
            return self.discussion_topics(topic_id=topic['topic_id'])[0]

    def handle_slack_event(self, event, reviewer=None):
        """Project a Slack thread reply and honor an explicit `close` command."""
        if not isinstance(event, dict):
            raise Invalid('invalid Slack event')
        message = event.get('message', event)
        channel, thread_ts = message.get('channel'), message.get('thread_ts')
        if not channel or not thread_ts:
            return {'ignored': True}
        topic = self.db.execute('SELECT * FROM discussion_topics WHERE slack_channel=? AND slack_thread_ts=?',
                                (channel, thread_ts)).fetchone()
        if topic is None:
            return {'ignored': True}
        text = (message.get('text') or '').strip()
        actor = message.get('user') or message.get('username') or 'slack-user'
        source_ref = message.get('ts') or message.get('event_ts')
        if text.lower().startswith('close') or ' close ' in f' {text.lower()} ':
            reason = text.split(None, 1)[1] if len(text.split(None, 1)) == 2 else 'Closed from Slack'
            return self.close_topic(topic['discussion_id'], actor, 'resolved', reason, reviewer)
        self.add_discussion_comment(topic['discussion_id'], actor, text, topic['topic_id'],
                                    topic['section_anchor'], topic['proposal_id'],
                                    source_ref=source_ref, mirror=False)
        return {'discussion_id': topic['discussion_id'], 'received': True}

    def add_discussion_comment(self, discussion_id, author, body, topic_id=None,
                               section_anchor=None, proposal_id=None, parent_comment_id=None,
                               status='open', source_ref=None, mirror=True):
        """Append a canonical comment with explicit topic, anchor and reply relation."""
        for value, label in ((discussion_id, 'discussion_id'), (author, 'author'), (body, 'body'),
                             (topic_id, 'topic_id'), (section_anchor, 'section_anchor')):
            if not isinstance(value, str) or not value.strip():
                raise Invalid(label + ' required')
        if status not in ('open', 'resolved', 'blocked', 'decision'):
            raise Invalid('invalid comment status')
        comment_id = digest((discussion_id + author + body + now()).encode())[:24]
        stamp = now()
        if source_ref and self.db.execute('SELECT 1 FROM discussion_comments WHERE discussion_id=? AND source_ref=?',
                                          (discussion_id, source_ref)).fetchone():
            return None
        with self.db:
            self.db.execute('''INSERT INTO discussion_comments VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',
                            (discussion_id, comment_id, parent_comment_id, topic_id, section_anchor,
                             proposal_id, author, body, status, stamp, stamp, source_ref))
            self.db.execute('UPDATE discussion_topics SET updated_at=? WHERE discussion_id=?',
                            (stamp, discussion_id))
        topic = self.db.execute('SELECT slack_channel,slack_thread_ts FROM discussion_topics WHERE discussion_id=?', (discussion_id,)).fetchone()
        if mirror and self.slack is not None and topic is not None and topic['slack_thread_ts']:
            self.slack.post({'channel': topic['slack_channel'], 'thread_ts': topic['slack_thread_ts']}, body)
        return comment_id

    def get_discussion(self, ident):
        """Read one proposal discussion and its complete append-only history."""
        with self.lock():
            row = self.row(ident)
            self.integrity(row)
            return self._workflow_discussion(row)

    def sync_slack_discussion(self, ident):
        """Collect new replies from the Slack thread into the workflow view.

        Slack remains the source of discussion text; the local rows are only a
        projection used to bind review/version checks to the frozen proposal.
        """
        if self.slack is None:
            raise Invalid('Slack discussion transport is not configured')
        with self.lock():
            row = self.row(ident)
            discussion = self.db.execute('SELECT * FROM discussions WHERE proposal_id=?', (ident,)).fetchone()
            if discussion is None or not discussion['slack_thread_ts']:
                raise Invalid('discussion does not have a Slack thread')
            thread = {'channel': discussion['slack_channel'], 'thread_ts': discussion['slack_thread_ts']}
            messages = self.slack.messages(thread)
            existing = self.db.execute('SELECT COUNT(*) FROM discussion_events WHERE proposal_id=?', (ident,)).fetchone()[0]
            for message in messages[existing:]:
                text = message.get('text', '').strip()
                if not text:
                    continue
                with self.db:
                    sequence = self.db.execute('SELECT COALESCE(MAX(sequence), 0)+1 FROM discussion_events WHERE proposal_id=?', (ident,)).fetchone()[0]
                    self.db.execute('INSERT INTO discussion_events VALUES(?,?,?,?,?,?,?,?,?)',
                                    (ident, sequence, message.get('user', 'slack-user'), message.get('ts', now()),
                                     'message', text, None, None, row['bundle_hash']))
                    self.db.execute('UPDATE discussions SET version=? WHERE proposal_id=?', (sequence, ident))
            return self._workflow_discussion(row)

    def sync_discord_discussion(self, ident):
        """Import Discord thread replies into the canonical local store."""
        if self.slack is None:
            raise Invalid('Discord discussion transport is not configured')
        with self.lock():
            row = self.row(ident)
            discussion = self.db.execute('SELECT * FROM discussions WHERE proposal_id=?', (ident,)).fetchone()
            if discussion is None or not discussion['discord_thread_id']:
                raise Invalid('discussion does not have a Discord thread')
            messages = self.slack.messages({'channel': discussion['discord_channel'],
                                            'thread_id': discussion['discord_thread_id']})
            existing = self.db.execute('SELECT COUNT(*) FROM discussion_events WHERE proposal_id=?', (ident,)).fetchone()[0]
            for message in reversed(messages):
                text = message.get('content', '').strip()
                if not text or existing and message.get('id') == discussion['discord_thread_id']:
                    continue
                actor = (message.get('author') or {}).get('username', 'discord-user')
                self.add_discussion_comment(ident, actor, text, ident, 'proposal', ident,
                                            parent_comment_id=None, source_ref=message.get('id'))
                with self.db:
                    sequence = self.db.execute('SELECT COALESCE(MAX(sequence), 0)+1 FROM discussion_events WHERE proposal_id=?', (ident,)).fetchone()[0]
                    self.db.execute('INSERT INTO discussion_events VALUES(?,?,?,?,?,?,?,?,?)',
                                    (ident, sequence, actor, message.get('timestamp', now()), 'message', text, None, None, row['bundle_hash']))
                    self.db.execute('UPDATE discussions SET version=? WHERE proposal_id=?', (sequence, ident))
            return self._workflow_discussion(row)

    def _current_discussion(self, ident, bundle_hash, version):
        row = self.row(ident)
        self.integrity(row)
        if row['state'] != 'pending' or not isinstance(bundle_hash, str) or bundle_hash != row['bundle_hash']:
            raise Invalid('discussion requires the current pending contribution')
        current = self._workflow_discussion(row)
        if current['discussion'] is None:
            raise Invalid('discussion has not been created')
        if type(version) is not int or version != current['workflow_discussion_version']:
            raise Conflict('discussion changed; reread the discussion')
        return row, current

    def _append_discussion_event(self, row, current, actor, action, message,
                                 agrees_with=None, decision=None, status=None):
        sequence = current['workflow_discussion_version'] + 1
        try:
            with self.db:
                if status is not None:
                    update = self.db.execute('UPDATE discussions SET status=?,version=? WHERE proposal_id=? AND version=?',
                                             (status, sequence, row['id'], current['workflow_discussion_version']))
                    if update.rowcount != 1:
                        raise sqlite3.IntegrityError()
                else:
                    update = self.db.execute('UPDATE discussions SET version=? WHERE proposal_id=? AND version=?',
                                             (sequence, row['id'], current['workflow_discussion_version']))
                    if update.rowcount != 1:
                        raise sqlite3.IntegrityError()
                self.db.execute('INSERT INTO discussion_events VALUES(?,?,?,?,?,?,?,?,?)',
                                (row['id'], sequence, actor, now(), action, message, agrees_with,
                                 decision, row['bundle_hash']))
        except sqlite3.IntegrityError as exc:
            raise Conflict('discussion changed; reread the discussion') from exc
        return self._workflow_discussion(row)

    def create_discussion(self, ident, actor, bundle_hash, reason):
        """Open a proposal discussion. An unresolved discussion holds approval."""
        with self.lock():
            row = self.row(ident)
            self.integrity(row)
            actor = self._discussion_actor(actor)
            reason = self._discussion_text(reason, 'discussion reason')
            if row['state'] != 'pending' or not isinstance(bundle_hash, str) or bundle_hash != row['bundle_hash']:
                raise Invalid('discussion requires the current pending contribution')
            if self._workflow_discussion(row)['discussion'] is not None:
                raise Invalid('discussion already exists; add a message or place it on hold')
            thread = None
            if self.slack is not None:
                thread = self.slack.open(row['id'], row['bundle_hash'], reason)
            try:
                with self.db:
                    self.db.execute('INSERT INTO discussions(proposal_id,bundle_hash,status,version,created_by,created_at) VALUES(?,?,?,?,?,?)',
                                    (row['id'], row['bundle_hash'], 'open', 1, actor, now()))
                    if thread:
                        if 'thread_ts' in thread:
                            self.db.execute('UPDATE discussions SET slack_channel=?, slack_thread_ts=? WHERE proposal_id=?',
                                            (thread['channel'], thread['thread_ts'], row['id']))
                        else:
                            self.db.execute('UPDATE discussions SET discord_channel=?, discord_thread_id=? WHERE proposal_id=?',
                                            (thread['channel'], thread['thread_id'], row['id']))
                    self.db.execute('INSERT INTO discussion_events VALUES(?,?,?,?,?,?,?,?,?)',
                                    (row['id'], 1, actor, now(), 'open', reason, None, None,
                                     row['bundle_hash']))
                    stamp = now()
                    self.db.execute('''INSERT INTO discussion_topics
                        (discussion_id,project_id,document_path,section_anchor,topic_id,parent_topic_id,proposal_id,author,body,status,created_at,updated_at,source_refs,slack_channel,slack_thread_ts,reviewer_notified)
                        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                        (row['id'], None, row['target'], 'proposal', row['id'], None, row['id'],
                         actor, reason, 'open', stamp, stamp, '[]',
                         thread['channel'] if thread and 'channel' in thread else None,
                         thread['thread_ts'] if thread and 'thread_ts' in thread else None, None))
            except sqlite3.IntegrityError as exc:
                raise Conflict('discussion already exists; reread the discussion') from exc
            return self._workflow_discussion(row)

    def add_discussion_message(self, ident, actor, bundle_hash, version, message, agrees_with=None):
        """Append evidence, an objection, or an explicit agreement to a discussion."""
        with self.lock():
            actor = self._discussion_actor(actor)
            message = self._discussion_text(message, 'discussion message')
            row, current = self._current_discussion(ident, bundle_hash, version)
            if current['discussion']['status'] != 'open':
                raise Invalid('discussion is resolved; reopen it before adding messages')
            if agrees_with is not None:
                if type(agrees_with) is not int or agrees_with < 1 or agrees_with > version:
                    raise Invalid('agreement must reference an existing discussion entry')
                action = 'agreement'
            else:
                action = 'message'
            if self.slack is not None:
                discussion = self.db.execute('SELECT * FROM discussions WHERE proposal_id=?', (ident,)).fetchone()
                if discussion is not None and discussion['slack_thread_ts']:
                    self.slack.post({'channel': discussion['slack_channel'], 'thread_ts': discussion['slack_thread_ts']}, message)
            self.add_discussion_comment(ident, actor, message, ident, 'proposal', ident,
                                        status='open')
            return self._append_discussion_event(row, current, actor, action, message, agrees_with)

    def hold_proposal(self, ident, actor, bundle_hash, version, reason):
        """Record that an existing unresolved discussion continues to hold approval."""
        with self.lock():
            actor = self._discussion_actor(actor)
            reason = self._discussion_text(reason, 'hold reason')
            row, current = self._current_discussion(ident, bundle_hash, version)
            if current['discussion']['status'] != 'open':
                raise Invalid('only an open discussion can be kept on hold')
            return self._append_discussion_event(row, current, actor, 'hold', reason)

    def resolve_discussion(self, ident, actor, bundle_hash, version, decision, reason):
        """Have the configured human reviewer resolve, reject, or retain the hold."""
        with self.lock():
            row, current = self._current_discussion(ident, bundle_hash, version)
            self.check_reviewer(row, actor)
            reason = self._discussion_text(reason, 'discussion decision reason')
            if decision not in ('resolved', 'rejected', 'on_hold'):
                raise Invalid('discussion decision must be resolved, rejected, or on_hold')
            if current['discussion']['status'] != 'open':
                raise Invalid('only an open discussion can be decided')
            # `on_hold` is an explicit reviewer decision but remains open, so
            # participants can continue adding evidence.
            return self._append_discussion_event(
                row, current, actor, 'resolve' if decision == 'resolved' else decision,
                reason, decision=decision, status='resolved' if decision == 'resolved'
                else ('rejected' if decision == 'rejected' else 'open'))

    def semantic_discussion(self, ident):
        row = self.row(ident)
        events = []
        disputed = False
        for item in self.db.execute(
                '''SELECT sequence,actor,time,action,reason,resolution_kind,
                   related_contribution_ids,bundle_hash
                   FROM semantic_discussions WHERE proposal_id=? ORDER BY sequence''', (ident,)):
            if item['bundle_hash'] != row['bundle_hash']:
                raise Invalid('semantic discussion is bound to another bundle')
            event = dict(item)
            try:
                event['related_contribution_ids'] = json.loads(event['related_contribution_ids'])
            except (TypeError, ValueError) as exc:
                raise Invalid('semantic discussion changed') from exc
            events.append(event)
            if item['action'] in ('open', 'reopen'):
                disputed = True
            elif item['action'] == 'resolve':
                disputed = False
        return dict(semantic_discussion=events,
                    discussion_version=events[-1]['sequence'] if events else 0,
                    disputed=disputed)

    def discuss(self, ident, actor, bundle_hash, discussion_version, action, reason,
                resolution_kind=None, related_contribution_ids=None):
        """Append reviewer deliberation without changing the frozen proposal."""
        with self.lock():
            row = self.row(ident)
            self.integrity(row)
            self.check_reviewer(row, actor)
            if row['state'] != 'pending' or bundle_hash != row['bundle_hash']:
                raise Invalid('discussion requires the current pending contribution')
            current = self.semantic_discussion(ident)
            if type(discussion_version) is not int or discussion_version != current['discussion_version']:
                raise Conflict('semantic discussion changed; reread the contribution')
            if action not in ('open', 'comment', 'resolve', 'reopen'):
                raise Invalid('invalid semantic discussion action')
            if not isinstance(reason, str) or not reason.strip() or len(reason.encode()) > LIMIT:
                raise Invalid('semantic discussion reason required')
            related = [] if related_contribution_ids is None else related_contribution_ids
            if (not isinstance(related, list) or len(related) > 50 or
                    any(not isinstance(value, str) or
                        not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}', value)
                        for value in related) or len(set(related)) != len(related)):
                raise Invalid('related contribution IDs must be unique valid IDs')
            if action == 'open' and current['semantic_discussion']:
                raise Invalid('use reopen for a previously recorded discussion')
            if action == 'reopen' and (not current['semantic_discussion'] or current['disputed']):
                raise Invalid('only a resolved discussion can be reopened')
            if action in ('comment', 'resolve') and not current['disputed']:
                raise Invalid('open a semantic dispute before commenting or resolving')
            allowed_resolutions = ('supported', 'scoped', 'attributed', 'not_a_conflict')
            if action == 'resolve':
                if resolution_kind not in allowed_resolutions:
                    raise Invalid('resolution kind required')
            elif resolution_kind is not None:
                raise Invalid('resolution kind is only valid for resolve')
            event = (ident, discussion_version + 1, actor, now(), action, reason,
                     resolution_kind, json.dumps(related), row['bundle_hash'])
            if self.slack is not None:
                workflow = self.db.execute('SELECT slack_channel,slack_thread_ts FROM discussions WHERE proposal_id=?', (ident,)).fetchone()
                if workflow is not None and workflow['slack_thread_ts']:
                    self.slack.post({'channel': workflow['slack_channel'], 'thread_ts': workflow['slack_thread_ts']},
                                    f'[{action}] {actor}: {reason}')
            try:
                with self.db:
                    self.db.execute('INSERT INTO semantic_discussions VALUES(?,?,?,?,?,?,?,?,?)', event)
            except sqlite3.IntegrityError as exc:
                raise Conflict('semantic discussion changed; reread the contribution') from exc
            return self.semantic_discussion(ident)

    def review(self, ident, actor, preview, approve, reason):
        with self.lock():
            row = self.row(ident)
            self.integrity(row)
            self.check_reviewer(row, actor)
            if row['state'] != 'pending' or preview['bundle_hash'] != row['bundle_hash']:
                raise Invalid('review is no longer current')
            discussion = self.semantic_discussion(ident)
            if (type(preview.get('discussion_version')) is not int or
                    preview['discussion_version'] != discussion['discussion_version']):
                raise Conflict('semantic discussion changed; reread the contribution')
            workflow_discussion = self._workflow_discussion(row)
            if (type(preview.get('workflow_discussion_version')) is not int or
                    preview['workflow_discussion_version'] != workflow_discussion['workflow_discussion_version']):
                raise Conflict('discussion changed; reread the contribution')
            if approve and (discussion['disputed'] or workflow_discussion['discussion_hold']):
                raise Conflict('unresolved discussion blocks approval')
            if not reason.strip():
                raise Invalid('decision reason required')
            artifact = self._artifact(row, actor, preview['time'])
            if artifact != preview['artifact']:
                raise Invalid('review artifact does not match the server preview')
            context = parse(row['manifest']).get('context')
            if approve and context is not None and proposal_context.freshness(self, context)['status'] != 'current':
                raise Conflict('proposal context is stale; read new context and reassess')
            decision = dict(actor=actor, time=preview['time'], reason=reason, approved=approve,
                            discussion_version=discussion['discussion_version'],
                            workflow_discussion_version=workflow_discussion['workflow_discussion_version'],
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
                      semantic_discussion=self.semantic_discussion(ident),
                      discussion=self._workflow_discussion(row),
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
                # A publish-time race is evidence for the reviewer.  Never
                # open a discussion (or contact Slack) from the worker's
                # read/write path.
                self.conflict(row)
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
        result = [dict(r) for r in self.db.execute(
            '''SELECT id,target,submitter,state,phase,error,bundle_hash,artifact_hash,
               COALESCE((SELECT action IN ('open','reopen') FROM semantic_discussions
                 WHERE proposal_id=proposals.id AND action!='comment'
                 ORDER BY sequence DESC LIMIT 1), 0) AS disputed
               FROM proposals ORDER BY rowid''')]
        for item in result:
            row = self.row(item['id'])
            workflow_discussion = self._workflow_discussion(row)
            item['discussion_hold'] = workflow_discussion['discussion_hold']
            item['disputed'] = bool(item['disputed']) or item['discussion_hold']
            item['conflict'] = self.conflict(row)
        return result

    def conflict(self, row):
        """Describe a head conflict without changing the published wiki.

        A contribution is always compared with the exact v1 bytes it read.  If
        another contribution has produced v2 meanwhile, v1 remains the merge
        base; we never destructively roll the wiki back just to display it.
        """
        if row['base'] is None:
            return None
        current = self.remote.read(row['target'])
        if current is None or digest(current['content']) == parse(row['manifest'])['base_hash']:
            return None
        published = None
        for item in self.db.execute(
                "SELECT id,artifact,artifact_hash FROM proposals WHERE target=? AND state='published' ORDER BY rowid DESC",
                (row['target'],)):
            if item['artifact_hash'] and digest(item['artifact']) == digest(current['content']):
                published = item['id']; break
        base_content = row['base'].decode()
        current_content = current['content'].decode()
        proposal_content = row['proposed'].decode()
        result = dict(status='concurrent-change', stale=True, proposal_id=row['id'], target=row['target'],
                    base_hash=parse(row['manifest'])['base_hash'], base_content=row['base'].decode(),
                    current_hash=digest(current['content']), current_content=current_content,
                    proposal_hash=digest(row['proposed']), proposal_content=proposal_content,
                    current_version=current.get('version'), current_contribution_id=published)
        result['diff'] = ''.join(difflib.unified_diff(base_content.splitlines(True), current_content.splitlines(True), fromfile='v1', tofile='v2'))
        result['proposal_diff'] = ''.join(difflib.unified_diff(base_content.splitlines(True), proposal_content.splitlines(True), fromfile='v1', tofile='proposal'))
        result['hunks'] = [dict(opcodes=[dict(tag=tag, base_start=i1, base_end=i2,
                                              current_start=j1, current_end=j2)
                                         for tag, i1, i2, j1, j2 in group])
                           for group in difflib.SequenceMatcher(
                               None, base_content.splitlines(True), current_content.splitlines(True)
                           ).get_grouped_opcodes(3)]
        return result

    def resolve_conflict(self, ident, actor, outcome, reason, merged_content=None):
        """Resolve a v1→v2 race by rejecting B or creating a fresh v2-based proposal."""
        with self.lock():
            row = self.row(ident); self.integrity(row); self.check_reviewer(row, actor)
            if outcome not in ('keep_current', 'use_incoming', 'merge'):
                raise Invalid('invalid conflict outcome')
            if not isinstance(reason, str) or not reason.strip():
                raise Invalid('conflict resolution reason required')
            conflict = self.conflict(row)
            if conflict is None:
                raise Invalid('contribution has no current conflict')
            if outcome == 'keep_current':
                with self.db:
                    self.db.execute("UPDATE proposals SET state='rejected', decision=? WHERE id=?",
                                    (json.dumps(dict(actor=actor, time=now(), reason=reason,
                                                     approved=False, conflict_outcome=outcome)), ident))
                replacement = None
            else:
                proposed = row['proposed'] if outcome == 'use_incoming' else (
                    merged_content.encode() if isinstance(merged_content, str) else None)
                if not proposed:
                    raise Invalid('merged content required')
                new_id = f"{ident}-merge-{now().replace('-', '').replace(':', '').replace('T', '')[:12]}"
                new_id = re.sub(r'[^A-Za-z0-9_-]', '', new_id)[:80]
                manifest = dict(schema_version=1, id=new_id, target=row['target'],
                                base_hash=conflict['current_hash'], proposed_hash=digest(proposed),
                                reason=reason, sources=parse(row['manifest']).get('sources', []))
                raw_manifest = json.dumps(manifest).encode()
                validate_bundle(raw_manifest, conflict['current_content'].encode(), proposed)
                try:
                    with self.db:
                        self.db.execute('''INSERT INTO proposals
                          (id,target,bundle_hash,manifest,base,proposed,submitter,state)
                          VALUES(?,?,?,?,?,?,?,'pending')''',
                          (new_id, row['target'], digest(raw_manifest), raw_manifest,
                           conflict['current_content'].encode(), proposed, row['submitter']))
                except sqlite3.IntegrityError as exc:
                    raise Conflict('replacement contribution ID already exists; retry') from exc
                replacement = new_id
                with self.db:
                    self.db.execute("UPDATE proposals SET state='rejected', decision=? WHERE id=?",
                                    (json.dumps(dict(actor=actor, time=now(), reason=reason,
                                                     approved=False, conflict_outcome=outcome,
                                                     replacement_id=replacement)), ident))
            with self.db:
                self.db.execute('INSERT OR REPLACE INTO conflict_resolutions VALUES(?,?,?,?,?,?,?,?)',
                                (ident, actor, outcome, conflict['base_hash'], conflict['current_hash'],
                                 replacement, reason, now()))
            return dict(proposal_id=ident, outcome=outcome, replacement_id=replacement,
                        base_hash=conflict['base_hash'], current_hash=conflict['current_hash'])

    def detail(self, ident):
        """Return JSON-ready proposal data for trusted review interfaces."""
        with self.lock():
            row = self.row(ident)
            self.integrity(row)
            manifest = parse(row['manifest'])
            return dict(id=row['id'], target=row['target'], submitter=row['submitter'],
                        state=row['state'], phase=row['phase'], error=row['error'],
                        **self.semantic_discussion(ident),
                        **self._workflow_discussion(row),
                        reason=manifest['reason'], sources=manifest.get('sources', []),
                        knowledge_change=manifest.get('knowledge_change'), context=manifest.get('context'),
                        context_documents=proposal_context.documents(self, manifest.get('context')),
                        context_status=proposal_context.freshness(self, manifest.get('context'),
                                                                  include_target=row['state'] != 'published'),
                        base=(row['base'] or b'').decode(), proposed=row['proposed'].decode(),
                        decision=parse(row['decision']) if row['decision'] else None,
                        conflict=self.conflict(row))

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
                        **self.semantic_discussion(ident),
                        **self._workflow_discussion(row),
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
                        decision=parse(row['decision']) if row['decision'] else None,
                        conflict=self.conflict(row))

    def backup(self, destination):
        with self.lock():
            destination = Path(destination)
            if destination.exists():
                raise Invalid('backup destination already exists')
            with sqlite3.connect(destination) as target:
                self.db.backup(target)
