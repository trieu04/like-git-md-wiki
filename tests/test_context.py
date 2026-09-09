import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from wiki_worker.common import Conflict, Invalid
from wiki_worker.core import Worker
from wiki_worker.fixture import FixtureRemote


class ContextTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.remote = FixtureRemote(root / 'remote.sqlite')
        self.worker = Worker(root / 'state', self.remote, 'reviewer-agent')
        self.addCleanup(self.remote.db.close)
        self.addCleanup(self.worker.db.close)
        self.put('source.md', b'Policy: 30 days')

    def put(self, path, content):
        old = self.remote.read(path)
        return self.remote.write(path, content, None if old is None else [old['item'], old['version']])

    def draft(self):
        result = self.worker.agent_context('page.md', ['source.md'])
        return dict(id='agent-edit', target='page.md', content='30 days',
                    submitter='author-agent', reason='Based on policy source', context=result['context'])

    def approve(self):
        preview = self.worker.preview('agent-edit', 'reviewer-agent')
        self.worker.review('agent-edit', 'reviewer-agent', preview, True, 'Evidence supports claim')

    def test_versions_are_observed_per_document_per_utc_day_and_survive_restart(self):
        with patch('wiki_worker.context.now', return_value='2026-01-01T12:00:00+00:00'):
            first = self.draft()['context']['sources'][0]
            self.assertEqual(first['version'], '20260101-1')
            self.assertEqual(self.draft()['context']['sources'][0], first)
            self.put('source.md', b'Policy: 7 days')
            self.assertEqual(self.draft()['context']['sources'][0]['version'], '20260101-2')
            self.put('source.md', b'Policy: 30 days')
            self.assertEqual(self.draft()['context']['sources'][0]['version'], '20260101-3')
        with patch('wiki_worker.context.now', return_value='2026-01-02T00:00:00+00:00'):
            self.assertEqual(self.draft()['context']['sources'][0]['version'], '20260101-3')
            self.put('source.md', b'Policy: 8 days')
            self.assertEqual(self.draft()['context']['sources'][0]['version'], '20260102-1')
        restarted = Worker(self.worker.root, self.remote, 'reviewer-agent')
        self.addCleanup(restarted.db.close)
        self.assertEqual(restarted.agent_context('page.md', ['source.md'])['context']['sources'][0]['version'], '20260102-1')

    def test_stale_draft_is_rejected_without_recapturing_source(self):
        data = self.draft()
        self.put('source.md', b'Policy: 7 days')
        with self.assertRaisesRegex(Conflict, 'stale'):
            self.worker.agent_propose(data)
        self.assertEqual(self.worker.status(), [])

    def test_changed_source_after_preview_blocks_approval_but_allows_rejection(self):
        self.worker.agent_propose(self.draft())
        preview = self.worker.preview('agent-edit', 'reviewer-agent')
        self.put('source.md', b'Policy: 7 days')
        with self.assertRaisesRegex(Conflict, 'stale'):
            self.worker.review('agent-edit', 'reviewer-agent', preview, True, 'Approve')
        detail = self.worker.detail('agent-edit')
        self.assertEqual(detail['context_status']['status'], 'stale')
        self.assertEqual(detail['context_documents'][1]['content'], 'Policy: 30 days')
        self.worker.review('agent-edit', 'reviewer-agent', preview, False, 'Source changed')
        self.assertEqual(self.worker.row('agent-edit')['state'], 'rejected')

    def test_changed_source_after_approval_blocks_publish(self):
        self.worker.agent_propose(self.draft())
        self.approve()
        self.put('source.md', b'Policy: 7 days')
        self.assertEqual(self.worker.publish('agent-edit'), 'stale')
        self.assertIsNone(self.remote.read('page.md'))

    def test_successful_agent_decision_publish_retry_and_backup(self):
        data = self.draft()
        self.worker.agent_propose(data)
        self.assertEqual(self.worker.row('agent-edit')['state'], 'pending')
        self.approve()
        self.assertEqual(self.worker.publish('agent-edit'), 'published')
        self.assertEqual(self.worker.agent_propose(data), 'agent-edit')
        self.assertEqual(self.worker.publish('agent-edit'), 'published')
        self.assertEqual(self.worker.detail('agent-edit')['context_status']['status'], 'current')
        destination = self.worker.root / 'backup.sqlite'
        self.worker.backup(destination)
        import sqlite3
        with sqlite3.connect(destination) as db:
            self.assertEqual(db.execute('SELECT content FROM document_versions WHERE path=?', ('source.md',)).fetchone()[0], b'Policy: 30 days')

    def test_forged_reference_and_snapshot_tampering_are_rejected(self):
        data = self.draft()
        forged = json.loads(json.dumps(data))
        forged['context']['sources'][0]['version'] = '20260101-999'
        with self.assertRaisesRegex(Invalid, 'snapshot'):
            self.worker.agent_propose(forged)
        self.worker.agent_propose(data)
        with self.worker.db:
            self.worker.db.execute("UPDATE document_versions SET content=? WHERE path='source.md'", (b'Tampered',))
        with self.assertRaisesRegex(Invalid, 'snapshot'):
            self.worker.preview('agent-edit', 'reviewer-agent')

    def test_missing_duplicate_sources_and_changed_target(self):
        for sources in [['missing.md'], ['source.md', 'source.md'], ['page.md']]:
            with self.assertRaises(Invalid):
                self.worker.agent_context('page.md', sources)
        data = self.draft()
        self.put('page.md', b'Concurrent new page')
        with self.assertRaises(Conflict):
            self.worker.agent_propose(data)

    def test_author_agent_cannot_self_review(self):
        data = self.draft()
        data['submitter'] = 'reviewer-agent'
        self.worker.agent_propose(data)
        with self.assertRaisesRegex(Invalid, 'self-review'):
            self.worker.preview('agent-edit', 'reviewer-agent')
