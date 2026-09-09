import json
import tempfile
import unittest
from pathlib import Path

from wiki_worker.core import FixtureRemote, Invalid, Worker, digest


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.remote = FixtureRemote(self.root / 'remote.sqlite')
        self.worker = Worker(self.root / 'state', self.remote, 'reviewer')
        self.addCleanup(self.remote.db.close)
        self.addCleanup(self.worker.db.close)

    def proposal(self, ident='p1', target='page.md', base=None, content=b'New content\n'):
        folder = self.root / ident
        folder.mkdir()
        if base is not None:
            (folder / 'base.md').write_bytes(base)
        (folder / 'proposed.md').write_bytes(content)
        manifest = dict(schema_version=1, id=ident, target=target,
                        base_hash=None if base is None else digest(base),
                        proposed_hash=digest(content), reason='Correct documentation', sources=['source'])
        (folder / 'proposal.ready.json').write_text(json.dumps(manifest))
        self.worker.scan(folder, 'contributor')
        return folder

    def approve(self, ident='p1'):
        preview = self.worker.preview(ident, 'reviewer')
        self.worker.review(ident, 'reviewer', preview, True, 'Checked source')
        return preview['artifact']

    def test_exact_artifact_retry_and_history(self):
        folder = self.proposal()
        self.worker.scan(folder, 'contributor')
        artifact = self.approve()
        self.assertEqual(self.worker.publish('p1'), 'published')
        self.assertEqual(self.worker.publish('p1'), 'published')
        self.assertEqual(self.remote.read('page.md')['content'], artifact)
        self.assertEqual(self.remote.db.execute('SELECT COUNT(*) FROM writes').fetchone()[0], 1)
        self.assertIsNotNone(self.worker.db.execute('SELECT * FROM history').fetchone())

    def test_competing_proposals(self):
        self.proposal()
        self.proposal('p2')
        self.approve()
        self.approve('p2')
        self.worker.publish('p1')
        self.assertEqual(self.worker.publish('p2'), 'stale')

    def test_race_after_read_cannot_overwrite(self):
        self.remote.write('page.md', b'Base', None)
        self.proposal(base=b'Base')
        self.approve()
        original = self.remote.write
        def race(target, content, expected):
            original(target, b'External edit', expected)
            return original(target, content, expected)
        self.remote.write = race
        self.assertEqual(self.worker.publish('p1'), 'stale')
        self.assertEqual(self.remote.read('page.md')['content'], b'External edit')

    def test_unknown_write_blocks_target_across_restart_only(self):
        self.proposal()
        self.proposal('p2')
        self.proposal('p3', target='other.md')
        for ident in ['p1', 'p2', 'p3']:
            self.approve(ident)
        original = self.remote.write
        def timeout(*args):
            original(*args)
            raise TimeoutError()
        self.remote.write = timeout
        with self.assertRaises(Invalid):
            self.worker.publish('p1')
        self.remote.write = original
        restarted = Worker(self.root / 'state', self.remote, 'reviewer')
        self.addCleanup(restarted.db.close)
        with self.assertRaisesRegex(Invalid, 'blocked'):
            restarted.publish('p2')
        self.assertEqual(restarted.publish('p3'), 'published')
        with self.assertRaises(Invalid):
            restarted.resolve('p1', 'reviewer', 'written', 'Content hash matches')
        receipt = self.remote.db.execute("SELECT receipt FROM writes WHERE target='page.md'").fetchone()[0]
        restarted.resolve('p1', 'reviewer', 'written', 'Checked fixture write ledger receipt', receipt)
        self.assertEqual(restarted.row('p1')['state'], 'published')
        self.assertEqual(restarted.publish('p2'), 'stale')

    def test_crash_and_history_failure_do_not_repeat_upload(self):
        self.proposal()
        self.approve()
        finish = self.worker.finish
        self.worker.finish = lambda ident: (_ for _ in ()).throw(OSError('history unavailable'))
        with self.assertRaises(OSError):
            self.worker.publish('p1')
        self.assertEqual(self.worker.row('p1')['phase'], 'written')
        self.worker.finish = finish
        self.worker.publish('p1')
        self.assertEqual(self.remote.db.execute('SELECT COUNT(*) FROM writes').fetchone()[0], 1)

    def test_create_race_preserves_external_file(self):
        self.proposal()
        self.approve()
        original = self.remote.write
        def race(target, content, expected):
            original(target, b'External create', None)
            return original(target, content, expected)
        self.remote.write = race
        self.assertEqual(self.worker.publish('p1'), 'stale')
        self.assertEqual(self.remote.read('page.md')['content'], b'External create')

    def test_failed_read_is_not_absence(self):
        self.proposal()
        self.approve()
        def denied(target):
            raise PermissionError('denied')
        self.remote.read = denied
        with self.assertRaises(PermissionError):
            self.worker.publish('p1')
        self.assertIsNone(self.worker.row('p1')['phase'])
        self.assertEqual(self.remote.db.execute('SELECT COUNT(*) FROM writes').fetchone()[0], 0)

    def test_review_rechecks_state_after_preview(self):
        self.proposal()
        preview = self.worker.preview('p1', 'reviewer')
        self.worker.review('p1', 'reviewer', preview, False, 'Needs changes')
        with self.assertRaises(Invalid):
            self.worker.review('p1', 'reviewer', preview, True, 'Old preview')

    def test_self_review_and_unknown_reviewer(self):
        self.proposal()
        with self.assertRaises(Invalid):
            self.worker.preview('p1', 'stranger')
        self.worker.reviewer = 'contributor'
        with self.assertRaisesRegex(Invalid, 'self-review'):
            self.worker.preview('p1', 'contributor')

    def test_mutation_duplicate_id_and_frozen_payload(self):
        folder = self.proposal()
        (folder / 'proposed.md').write_bytes(b'Altered')
        with self.assertRaises(Invalid):
            self.worker.scan(folder, 'contributor')
        self.assertIn(b'New content', self.approve())
        with self.worker.db:
            self.worker.db.execute("UPDATE proposals SET artifact=?", (b'tampered',))
        with self.assertRaisesRegex(Invalid, 'artifact changed'):
            self.worker.publish('p1')

    def test_duplicate_json_keys_and_path_rejected(self):
        folder = self.proposal()
        manifest = folder / 'proposal.ready.json'
        raw = manifest.read_text()
        manifest.write_text(raw[:-1] + ',"id":"p1"}')
        with self.assertRaisesRegex(Invalid, 'duplicate'):
            self.worker.scan(folder, 'contributor')
        from wiki_worker.core import target_path
        for path in ['../x.md', '/x.md', 'a//x.md', 'A.md', 'con.md', 'a%2fb.md', 'a\\b.md']:
            with self.assertRaises(Invalid):
                target_path(path)

    def test_restore_is_new_review_without_old_marker(self):
        self.proposal()
        old = self.approve()
        self.worker.publish('p1')
        with self.assertRaisesRegex(Invalid, 'marker'):
            self.proposal('invalid', base=old, content=old)
        self.proposal('restore', base=old, content=b'Original content')
        artifact = self.approve('restore')
        self.worker.publish('restore')
        self.assertEqual(artifact.count(b'<!-- wiki-review: start -->'), 1)
        self.assertNotIn(b'Proposal: p1', artifact)

    def test_backup_keeps_bundle_history_and_uncertain_intent(self):
        self.proposal()
        self.approve()
        def crash(*args):
            raise KeyboardInterrupt()
        self.remote.write = crash
        with self.assertRaises(KeyboardInterrupt):
            self.worker.publish('p1')
        destination = self.root / 'backup.sqlite'
        self.worker.backup(destination)
        import sqlite3
        with sqlite3.connect(destination) as db:
            row = db.execute('SELECT phase,proposed,artifact FROM proposals').fetchone()
            self.assertEqual(row[0], 'writing')
            self.assertEqual(row[1], b'New content\n')
            self.assertIsNotNone(row[2])


if __name__ == '__main__':
    unittest.main()
