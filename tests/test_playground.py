import tempfile
import unittest
from pathlib import Path

from scripts.semantic_conflict_playground import seed
from wiki_worker.core import Worker
from wiki_worker.local import LocalFolderStorage


class PlaygroundTests(unittest.TestCase):
    def test_seed_creates_open_and_resolved_semantic_examples(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            wiki = seed(root, 'reviewer-agent')
            worker = Worker(root / 'state', LocalFolderStorage(wiki), 'reviewer-agent')
            try:
                queue = {item['id']: item for item in worker.status()}
                self.assertTrue(queue['redis-disputed']['disputed'])
                self.assertFalse(queue['redis-scoped']['disputed'])
                self.assertFalse(queue['redis-discussion']['disputed'])
                disputed = worker.contribution('redis-disputed')
                scoped = worker.contribution('redis-scoped')
                self.assertEqual(disputed['discussion_version'], 1)
                self.assertEqual(scoped['discussion_version'], 3)
                self.assertEqual(scoped['semantic_discussion'][-1]['resolution_kind'], 'scoped')
            finally:
                worker.db.close()


if __name__ == '__main__':
    unittest.main()
