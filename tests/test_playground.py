import tempfile
import unittest
from pathlib import Path

from scripts.semantic_conflict_playground import seed
from wiki_worker.core import Worker
from wiki_worker.local import LocalFolderStorage


class PlaygroundTests(unittest.TestCase):
    def test_seed_creates_focused_concurrent_and_semantic_examples(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            wiki = seed(root, 'reviewer-agent')
            worker = Worker(root / 'state', LocalFolderStorage(wiki), 'reviewer-agent')
            try:
                queue = {item['id']: item for item in worker.status()}
                self.assertEqual(set(queue), {
                    'contribution-a', 'contribution-b', 'contribution-c', 'color-red'})
                self.assertEqual(queue['contribution-a']['state'], 'published')
                for ident in ('contribution-b', 'contribution-c'):
                    evidence = worker.contribution(ident)['conflict']
                    self.assertEqual(evidence['status'], 'concurrent-change')
                    self.assertEqual(evidence['current_contribution_id'], 'contribution-a')
                self.assertEqual(worker.discussion_topics(document_path='shared-guide.md'), [])
                color = worker.contribution('color-red')
                self.assertTrue(color['disputed'])
                self.assertIsNone(color['conflict'])
                self.assertIn('What is the approved production color for X?',
                              color['semantic_discussion'][0]['reason'])
            finally:
                worker.db.close()


if __name__ == '__main__':
    unittest.main()
