import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class CliTests(unittest.TestCase):
    def test_scan_path_does_not_override_wiki_folder(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            wiki = root / 'wiki'
            wiki.mkdir()
            bundle = root / 'bundle'
            bundle.mkdir()
            (bundle / 'proposal.ready.json').write_text(
                '{"schema_version":1,"id":"cli-scan","target":"new.md",'
                '"base_hash":null,'
                '"proposed_hash":"f676b43bd55f91451babc1663739064abb7e11e2b5f4a7efe62c29e4eeb0d117",'
                '"reason":"CLI regression"}',
                encoding='utf-8',
            )
            (bundle / 'proposed.md').write_text('# New\n', encoding='utf-8')

            result = subprocess.run(
                [sys.executable, '-m', 'wiki_worker.cli', '--state', str(root / 'state'),
                 '--folder', str(wiki), '--reviewer', 'reviewer', 'scan', str(bundle),
                 '--submitter', 'author'],
                check=False, capture_output=True, text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), 'cli-scan')


if __name__ == '__main__':
    unittest.main()
