import tempfile
import unittest
from pathlib import Path

from scripts.stroke_demo_playground import initialize, write_seed_wiki
from wiki_worker.core import Worker
from wiki_worker.local import LocalFolderStorage


class StrokeDemoTests(unittest.TestCase):
    def test_multiple_contributors_and_semantic_conflict(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            wiki = root / 'wiki-demo-stroke'
            write_seed_wiki(wiki)
            state = root / 'state'
            initialize(wiki, state)
            worker = Worker(state, LocalFolderStorage(wiki), 'reviewer-agent')
            try:
                queue = {item['id']: item for item in worker.status()}
                self.assertEqual(queue['contribution-A-stroke-risk-factor']['state'], 'published')
                self.assertEqual(queue['contribution-A-stroke-risk-factor']['submitter'],
                                 'contributor-a')
                for ident in ('contribution-B-stroke-fast-detail',
                              'contribution-C-stroke-prevention-habits'):
                    view = worker.contribution(ident)
                    self.assertEqual(view['state'], 'pending')
                    self.assertEqual(view['context_status']['status'], 'stale')
                    self.assertEqual(view['conflict']['current_contribution_id'],
                                     'contribution-A-stroke-risk-factor')
                conflict = worker.contribution('contribution-D-stroke-wait-30-minutes')
                self.assertEqual(conflict['submitter'], 'contributor-d')
                self.assertEqual(conflict['context_status']['status'], 'current')
                self.assertTrue(conflict['disputed'])
                self.assertIn('no supporting versioned evidence',
                              conflict['semantic_discussion'][0]['reason'])
            finally:
                worker.db.close()


if __name__ == '__main__':
    unittest.main()
