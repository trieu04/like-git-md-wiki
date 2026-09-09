import json
import tempfile
import unittest
from pathlib import Path

from wiki_worker.common import Conflict, Invalid, digest
from wiki_worker.core import Worker
from wiki_worker.local import LocalFolderStorage


class LocalStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.storage = LocalFolderStorage(self.root / 'wiki')
        self.worker = Worker(self.root / 'state', self.storage, 'reviewer')
        self.addCleanup(self.worker.db.close)

    def approve(self, ident):
        preview = self.worker.preview(ident, 'reviewer')
        self.worker.review(ident, 'reviewer', preview, True, 'Checked')
        return preview['artifact']

    def test_plain_markdown_end_to_end(self):
        self.worker.propose('new', 'guide/index.md', b'# Guide\n', 'author', 'Add guide')
        artifact = self.approve('new')
        self.assertEqual(self.worker.publish('new'), 'published')
        self.assertEqual((self.root / 'wiki/guide/index.md').read_bytes(), artifact)
        self.assertEqual(self.storage.list_markdown(), ['guide/index.md'])
        self.worker.propose('edit', 'guide/index.md', b'# Updated\n', 'author', 'Update guide')
        updated = self.approve('edit')
        self.assertEqual(self.worker.row('edit')['base'], artifact)
        self.worker.publish('edit')
        self.assertEqual(self.storage.read('guide/index.md')['content'], updated)
        self.assertEqual(self.worker.publish('edit'), 'published')
        self.assertEqual(len(list(self.storage.receipts.glob('*.json'))), 2)

    def test_listing_excludes_incoming_contributions_and_internal_files(self):
        self.storage.write('guide.md', b'# Guide', None)
        inbox = self.root / 'wiki/contributions'
        inbox.mkdir()
        (inbox / 'XX123.contribution.md').write_text('# Incoming contribution')
        (self.storage.control / 'internal.md').write_text('# Internal state')
        self.assertEqual(self.storage.list_markdown(), ['guide.md'])

    def test_conditional_versions_are_opaque_and_create_does_not_replace(self):
        first = self.storage.write('a.md', b'First', None)
        with self.assertRaises(Conflict):
            self.storage.write('a.md', b'Unexpected', None)
        second = self.storage.write('a.md', b'Second', [first['item'], first['version']])
        with self.assertRaises(Conflict):
            self.storage.write('a.md', b'Unexpected', [first['item'], first['version']])
        self.assertEqual(self.storage.read('a.md')['content'], b'Second')
        self.assertTrue(self.storage.verify(second))

    def test_existing_folder_edit_is_detected(self):
        (self.root / 'wiki/a.md').write_bytes(b'Existing markdown')
        self.worker.propose('edit', 'a.md', b'New', 'author', 'Update')
        self.approve('edit')
        (self.root / 'wiki/a.md').write_bytes(b'External edit')
        self.assertEqual(self.worker.publish('edit'), 'stale')
        self.assertEqual((self.root / 'wiki/a.md').read_bytes(), b'External edit')

    def test_symlink_escape_rejected(self):
        outside = self.root / 'outside'
        outside.mkdir()
        (outside / 'a.md').write_bytes(b'Private')
        (self.root / 'wiki/link').symlink_to(outside, target_is_directory=True)
        with self.assertRaises(Invalid):
            self.storage.read('link/a.md')
        with self.assertRaises(Invalid):
            self.storage.write('link/a.md', b'Overwrite', None)
        self.assertEqual((outside / 'a.md').read_bytes(), b'Private')

    def test_uncertain_write_resolves_without_database_dependency(self):
        self.worker.propose('new', 'a.md', b'New', 'author', 'Add')
        self.approve('new')
        original = self.storage.write
        def timeout(*args):
            original(*args)
            raise TimeoutError()
        self.storage.write = timeout
        with self.assertRaises(Invalid):
            self.worker.publish('new')
        restarted = Worker(self.root / 'state', LocalFolderStorage(self.root / 'wiki'), 'reviewer')
        self.addCleanup(restarted.db.close)
        receipt = next(self.storage.receipts.glob('*.json')).stem
        restarted.resolve('new', 'reviewer', 'written', 'Verified durable operation receipt', receipt)
        self.assertEqual(restarted.row('new')['state'], 'published')
        self.assertEqual(len(list(self.storage.receipts.glob('*.json'))), 1)

    def test_adapter_can_submit_bytes_without_local_inbox(self):
        content = b'# From an adapter\n'
        manifest = json.dumps(dict(schema_version=1, id='remote', target='remote.md',
            base_hash=None, proposed_hash=digest(content), reason='Submit bytes')).encode()
        self.worker.submit(manifest, None, content, 'trusted-adapter-account')
        self.assertEqual(self.worker.row('remote')['proposed'], content)
        self.assertEqual(self.worker.row('remote')['submitter'], 'trusted-adapter-account')
