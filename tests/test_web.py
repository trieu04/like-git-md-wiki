import json
import shutil
import subprocess
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from wiki_worker.common import digest
from wiki_worker.web import Application, Handler


class WebTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        wiki = self.root / 'wiki'
        wiki.mkdir()
        (wiki / 'index.md').write_text('# Wiki\n')
        (wiki / 'source.md').write_text('Source v1\n')
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.application = Application(self.root / 'state', wiki, None, 'reviewer', 'Owner')
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.base = f'http://127.0.0.1:{self.server.server_port}'

    def request(self, path, method='GET', body=None):
        request = urllib.request.Request(self.base + path, data=None if body is None else json.dumps(body).encode(),
                                         method=method, headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(request) as response:
            return response.status, json.loads(response.read())

    def capture(self):
        worker = self.server.application.worker()
        try:
            return worker.agent_context('index.md', ['source.md'])
        finally:
            self.server.application.close(worker)

    def file(self):
        captured = self.capture()
        base = '# Wiki\n'
        proposed = '# Updated\n'
        target, source = captured['context']['target'], captured['context']['sources'][0]
        return f'''# Wiki contribution

| Field | Value |
| --- | --- |
| Format | wiki-contribution-v3 |
| Boundary | wc-test |
| ID | contribution-1 |
| Base SHA-256 | {digest(base.encode())} |
| Proposed SHA-256 | {digest(proposed.encode())} |
| Author | informational-author |
| Reason | Source checked |

## Scope and impact files

| File | Version | Impact |
| --- | --- | --- |
| {target['path']} | {target['version']} | Update heading |

## Sources

| File | Version |
| --- | --- |
| {source['path']} | {source['version']} |

## Proposed content

--- wc-test:proposed ---

{proposed}

--- wc-test:base ---

## Base content

{base}

--- wc-test:end ---
'''

    def ingest(self, envelope=None, author='author'):
        return self.request('/api/contribution/import', 'POST',
                            {'file': envelope or self.file(), 'submitter': author})

    def test_file_import_combined_read_review_publish(self):
        envelope = self.file()
        _, queue = self.request('/api/contribution')
        self.assertEqual(queue, [])
        status, created = self.ingest(envelope)
        self.assertEqual(status, 201)
        self.assertEqual(created['id'], 'contribution-1')
        _, view = self.request('/api/contribution/contribution-1')
        self.assertEqual(view['submitter'], 'author')
        self.assertEqual(view['context_status']['status'], 'current')
        self.assertEqual(view['context_documents'][1]['content'], 'Source v1\n')
        self.assertEqual(view['proposed'], '# Updated\n')
        self.assertIn('# Updated', view['artifact'])
        self.assertIn('diff', view)
        self.assertTrue(view['can_review'])
        self.request('/api/contribution/contribution-1/review', 'POST',
                     {**view, 'actor': 'reviewer', 'reason': 'Verified content', 'approve': True})
        _, saved = self.request('/api/contribution/contribution-1')
        self.assertEqual(saved['artifact'], view['artifact'])
        self.assertFalse(saved['can_review'])
        _, result = self.request('/api/contribution/contribution-1/publish', 'POST', {})
        self.assertEqual(result['state'], 'published')
        self.assertIn('# Updated', (self.root / 'wiki/index.md').read_text())

    def test_versions_track_concurrent_edits_metadata_and_exact_artifacts(self):
        envelope = self.file().replace('| Reason | Source checked |',
            '| Reason | Source checked |\n| Author role | Engineer |\n| Author expert | Policies |')
        self.ingest(envelope)
        self.ingest(envelope.replace('| contribution-1 |', '| contribution-2 |'), author='second-author')
        views = []
        for ident in ('contribution-1', 'contribution-2'):
            _, view = self.request('/api/contribution/' + ident)
            self.assertEqual(view['author_metadata'], {'role': 'Engineer', 'expert': 'Policies'})
            views.append(view)
            self.request('/api/contribution/' + ident + '/review', 'POST',
                         {**view, 'actor': 'reviewer', 'reason': 'Checked', 'approve': True})
        self.request('/api/contribution/contribution-1/publish', 'POST', {})
        _, result = self.request('/api/contribution/contribution-2/publish', 'POST', {})
        self.assertEqual(result['state'], 'stale')
        _, history = self.request('/api/wiki/versions?path=index.md')
        self.assertEqual(len(history['versions']), 2)
        self.assertEqual([c['state'] for c in history['changes']], ['published', 'stale'])
        self.assertIn('-# Wiki', history['changes'][0]['diff'])
        self.assertEqual(history['changes'][0]['publication']['published_version']['version'],
                         history['versions'][1]['version'])
        for reference, expected in zip(history['versions'], ['# Wiki\n', views[0]['artifact']]):
            _, snapshot = self.request('/api/wiki/version?path=index.md&version=' + reference['version'])
            self.assertEqual(snapshot['content'], expected)
            self.assertEqual(snapshot['hash'], digest(expected.encode()))
        self.request('/api/contribution/contribution-1/publish', 'POST', {})
        _, retry = self.request('/api/wiki/versions?path=index.md')
        self.assertEqual(retry, history)
        for query in ('path=..%2Fsecret.md', 'path=index.md&version=unknown'):
            with self.assertRaises(urllib.error.HTTPError) as caught:
                self.request('/api/wiki/version?' + query)
            self.assertEqual(caught.exception.code, 400)

    @unittest.skipUnless(shutil.which('node'), 'Node.js is required for browser export integration')
    def test_browser_generated_file_is_accepted_without_author_api(self):
        script = r'''
const fs = require('node:fs'), vm = require('node:vm');
const sandbox = {crypto: require('node:crypto').webcrypto, TextEncoder, setTimeout};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync('wiki_worker/static/app.js', 'utf8'), sandbox);
(async () => {
  const app = sandbox.wikiApp();
  const input = JSON.parse(fs.readFileSync(0, 'utf8'));
  app.selectedReference = input.target;
  app.documentContent = '# Wiki\n';
  Object.assign(app.form, {id:'browser-file', submitter:'author', reason:'Update heading',
    content:'# Updated\n', scopeFiles:`${input.target.path} | ${input.target.version} | Update heading`,
    sourceFiles:`${input.source.path} | ${input.source.version}`});
  await app.createFile();
  if (app.error) throw new Error(app.notice);
  process.stdout.write(app.generated.text);
})().catch(e => { console.error(e); process.exitCode = 1; });
'''
        captured = self.capture()['context']
        file_text = subprocess.check_output(['node', '-e', script],
                                            input=json.dumps({'target': captured['target'], 'source': captured['sources'][0]}).encode(),
                                            cwd=Path(__file__).resolve().parent.parent).decode()
        _, queue = self.request('/api/contribution')
        self.assertEqual(queue, [])
        _, imported = self.request('/api/contribution/import', 'POST', {'file': file_text, 'submitter': 'author'})
        _, view = self.request('/api/contribution/' + imported['id'])
        self.assertEqual(view['proposed'], '# Updated\n')
        self.assertEqual(view['context_status']['status'], 'current')
        self.assertEqual(view['scope_impact'], [
            {'path': 'index.md', 'version': captured['target']['version'], 'impact': 'Update heading'}])
        self.assertEqual(view['source_references'], [
            {'path': 'source.md', 'version': captured['sources'][0]['version']}])

    def test_scan_accepts_file_and_existing_bundle(self):
        envelope = self.file()
        path = self.root / 'change.contribution.md'
        path.write_text(envelope)
        worker = self.server.application.worker()
        try:
            self.assertEqual(worker.scan(path, 'author'), 'contribution-1')
            folder = self.root / 'bundle'
            folder.mkdir()
            captured = self.capture()
            manifest = dict(schema_version=1, id='bundle-1', target='index.md',
                            base_hash=digest(b'# Wiki\n'), proposed_hash=digest(b'# Bundle\n'),
                            reason='Bundle compatibility', context=captured['context'])
            (folder / 'base.md').write_text('# Wiki\n')
            (folder / 'proposed.md').write_text('# Bundle\n')
            (folder / 'proposal.ready.json').write_text(json.dumps(manifest))
            self.assertEqual(worker.scan(folder, 'author'), 'bundle-1')
            incoming = self.root / 'incoming'
            incoming.mkdir()
            (incoming / 'second.contribution.md').write_text(
                envelope.replace('| contribution-1 |', '| contribution-2 |'))
            self.assertEqual(worker.scan(incoming, 'author'), ['contribution-2'])
            self.assertEqual(len(worker.status()), 3)
        finally:
            self.server.application.close(worker)

    def test_plain_contribution_preserves_bytes_and_rejects_bad_breaks(self):
        from wiki_worker.core import contribution_file
        worker = self.server.application.worker()
        self.addCleanup(self.server.application.close, worker)
        ref = self.capture()['context']['target']
        for proposed in ['Tiếng Việt\n\n---\n## Base content\n<!-- contribution:base:end -->',
                         'CRLF\r\nline\r\n', 'Trailing\n\n', '']:
            base = '# Wiki\n'
            text = f'''# Wiki contribution

| Field | Value |
| --- | --- |
| Format | wiki-contribution-v3 |
| Boundary | wc-test |
| ID | plain |
| Base SHA-256 | {digest(base.encode())} |
| Proposed SHA-256 | {digest(proposed.encode())} |
| Author | author |
| Reason | Check plain payload |

## Scope and impact files

| File | Version | Impact |
| --- | --- | --- |
| index.md | {ref['version']} | Update |

## Sources

| File | Version |
| --- | --- |


## Proposed content

--- wc-test:proposed ---

{proposed}

--- wc-test:base ---

## Base content

{base}

--- wc-test:end ---
'''
            _, (_, _, actual_base, actual_proposed) = contribution_file(text.encode(), worker)
            self.assertEqual(actual_base, base.encode())
            self.assertEqual(actual_proposed, proposed.encode())
            from wiki_worker.common import Invalid
            for bad in [text.replace('--- wc-test:base ---', '---'),
                        text + 'extra', text.replace('--- wc-test:end ---', '--- wc-test:base ---'),
                        text.replace('## Proposed content\n', '## Proposed content\nwc-test\n')]:
                with self.assertRaises(Invalid):
                    contribution_file(bad.encode(), worker)

    def test_stale_file_and_malformed_or_tampered_files_fail(self):
        envelope = self.file()
        for bad in [envelope.replace('# Updated', '# Tampered'),
                    *(envelope.replace('wiki-contribution-v3', version) for version in
                      ('wiki-contribution-v1', 'wiki-contribution-v2', 'bad-format')),
                    '# not a contribution\n']:
            with self.assertRaises(urllib.error.HTTPError) as caught:
                self.ingest(bad)
            self.assertEqual(caught.exception.code, 400)
        (self.root / 'wiki/source.md').write_text('Source v2\n')
        with self.assertRaises(urllib.error.HTTPError):
            self.ingest(envelope)
        _, queue = self.request('/api/contribution')
        self.assertEqual(queue, [])

    def test_artifact_tampering_and_source_change_block_review(self):
        self.ingest()
        _, view = self.request('/api/contribution/contribution-1')
        with self.assertRaises(urllib.error.HTTPError):
            self.request('/api/contribution/contribution-1/review', 'POST',
                {**view, 'artifact': 'Tampered', 'actor': 'reviewer', 'reason': 'Review', 'approve': True})
        (self.root / 'wiki/source.md').write_text('Source changed\n')
        with self.assertRaises(urllib.error.HTTPError):
            self.request('/api/contribution/contribution-1/review', 'POST',
                {**view, 'actor': 'reviewer', 'reason': 'Review', 'approve': True})
        self.request('/api/contribution/contribution-1/review', 'POST',
                {**view, 'actor': 'reviewer', 'reason': 'Source changed', 'approve': False})

    def test_self_author_can_inspect_but_not_review(self):
        self.ingest(author='reviewer')
        _, view = self.request('/api/contribution/contribution-1')
        self.assertFalse(view['can_review'])
        self.assertIsNotNone(view['artifact'])
        with self.assertRaises(urllib.error.HTTPError):
            self.request('/api/contribution/contribution-1/review', 'POST',
                {**view, 'actor': 'reviewer', 'reason': 'Self review', 'approve': True})

    def test_old_discovery_author_and_preview_routes_are_removed(self):
        for route, method in [('/api/documents', 'GET'), ('/api/feedback/search', 'POST'),
                              ('/api/agent/context', 'POST'), ('/api/agent/proposals', 'POST'),
                              ('/api/proposals', 'GET'), ('/api/contribution/x/preview', 'GET')]:
            with self.assertRaises(urllib.error.HTTPError) as caught:
                self.request(route, method, {} if method == 'POST' else None)
            self.assertEqual(caught.exception.code, 404)

    def test_skill_and_ui_roles_are_served(self):
        _, skill = self.request('/api/skill')
        self.assertEqual(skill['contributor']['filename'], 'wiki-contributor-skill.md')
        self.assertEqual(skill['reviewer']['filename'], 'wiki-reviewer-skill.md')
        expected = {'contributor': '# For agent contributor',
                    'reviewer': '# Reviewer: worker, decisions and publication'}
        for role in ('contributor', 'reviewer'):
            with urllib.request.urlopen(self.base + skill[role]['download']) as response:
                body = response.read().decode()
                self.assertEqual(response.headers.get_content_type(), 'text/markdown')
                self.assertIn(f'filename="{skill[role]["filename"]}"',
                              response.headers['Content-Disposition'])
                self.assertTrue(body.startswith(f'---\nname: wiki-{role}\n'))
                self.assertIn(expected[role], body)
                self.assertNotIn('## For reviewer' if role == 'contributor' else '# For agent contributor', body)
        for path in ['/', '/app.js']:
            with urllib.request.urlopen(self.base + path) as response:
                self.assertEqual(response.status, 200)

    def test_sidebar_file_tree_data_and_document_read(self):
        nested = self.root / 'wiki/docs'
        nested.mkdir()
        (nested / 'guide.md').write_text('# Guide\n')
        _, paths = self.request('/api/wiki')
        self.assertEqual(paths, ['docs/guide.md', 'index.md', 'source.md'])
        _, document = self.request('/api/wiki/document?path=docs%2Fguide.md')
        self.assertEqual(document['path'], 'docs/guide.md')
        self.assertEqual(document['content'], '# Guide\n')
        self.assertEqual(document['reference']['path'], 'docs/guide.md')
        self.assertRegex(document['reference']['version'], r'^\d{8}-\d+$')
        self.assertEqual(document['reference']['hash'], digest(b'# Guide\n'))
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.request('/api/wiki/document?path=..%2Fsecret.md')
        self.assertEqual(caught.exception.code, 400)


if __name__ == '__main__':
    unittest.main()
