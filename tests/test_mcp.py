import io
import json
import tempfile
import unittest
from pathlib import Path

from wiki_worker.common import digest
from wiki_worker.core import Worker
from wiki_worker.fixture import FixtureRemote
from wiki_worker.mcp import DiscussionMCP, serve


class DiscussionMCPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.remote = FixtureRemote(root / 'remote.sqlite')
        self.worker = Worker(root / 'state', self.remote, 'reviewer')
        self.server = DiscussionMCP(self.worker)
        self.addCleanup(self.worker.db.close)
        self.addCleanup(self.remote.db.close)

    def call(self, name, arguments, request_id=1):
        return self.server.handle({
            'jsonrpc': '2.0', 'id': request_id, 'method': 'tools/call',
            'params': {'name': name, 'arguments': arguments},
        })['result']

    def test_lists_tools_and_manages_topic_discussion(self):
        listed = self.server.handle({
            'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list', 'params': {},
        })
        names = {item['name'] for item in listed['result']['tools']}
        self.assertIn('discussion_create', names)
        self.assertIn('proposal_discussion_resolve', names)

        created = self.call('discussion_create', {
            'project_id': 'wiki', 'document_path': 'policy.md',
            'section_anchor': 'deadline', 'topic_id': 'deadline-question',
            'author': 'facilitator', 'body': 'Which deadline applies?',
        })
        discussion_id = created['structuredContent']['discussion_id']
        comment = self.call('discussion_comment', {
            'discussion_id': discussion_id, 'author': 'domain-expert',
            'body': 'The policy source says 30 days.',
            'topic_id': 'deadline-question', 'section_anchor': 'deadline',
        })
        self.assertIsNotNone(comment['structuredContent']['comment_id'])
        found = self.call('discussion_list', {'discussion_id': discussion_id})
        topics = found['structuredContent']['discussions']
        self.assertEqual(len(topics), 1)
        self.assertEqual(topics[0]['comments'][0]['author'], 'domain-expert')
        closed = self.call('discussion_close', {
            'discussion_id': discussion_id, 'actor': 'facilitator',
            'outcome': 'resolved', 'reason': 'Source owner confirmed.',
        })
        self.assertEqual(closed['structuredContent']['status'], 'resolved')

    def test_tool_domain_error_is_mcp_tool_error(self):
        result = self.call('discussion_close', {
            'discussion_id': 'missing', 'actor': 'facilitator',
            'outcome': 'resolved', 'reason': 'Done',
        })
        self.assertTrue(result['isError'])
        self.assertIn('unknown discussion', result['content'][0]['text'])

    def test_proposal_discussion_preserves_version_and_reviewer_checks(self):
        bundle = Path(self.temp.name) / 'bundle'
        bundle.mkdir()
        content = b'# Proposed\n'
        (bundle / 'proposed.md').write_bytes(content)
        (bundle / 'proposal.ready.json').write_text(json.dumps({
            'schema_version': 1, 'id': 'proposal-1', 'target': 'policy.md',
            'base_hash': None, 'proposed_hash': digest(content),
            'reason': 'Document the policy',
        }))
        self.worker.scan(bundle, 'author')
        proposal = self.worker.contribution('proposal-1')
        common = {'proposal_id': 'proposal-1', 'bundle_hash': proposal['bundle_hash']}

        opened = self.call('proposal_discussion_create', {
            **common, 'actor': 'domain-expert', 'reason': 'The scope needs evidence.',
        })['structuredContent']
        self.assertTrue(opened['discussion_hold'])
        messaged = self.call('proposal_discussion_message', {
            **common, 'actor': 'author', 'discussion_version': 1,
            'message': 'The wording is limited to this policy.', 'agrees_with': 1,
        })['structuredContent']
        self.assertEqual(messaged['workflow_discussion_version'], 2)

        denied = self.call('proposal_discussion_resolve', {
            **common, 'actor': 'not-reviewer', 'discussion_version': 2,
            'decision': 'resolved', 'reason': 'Looks good.',
        })
        self.assertTrue(denied['isError'])
        resolved = self.call('proposal_discussion_resolve', {
            **common, 'actor': 'reviewer', 'discussion_version': 2,
            'decision': 'resolved', 'reason': 'Scope and evidence are now explicit.',
        })['structuredContent']
        self.assertFalse(resolved['discussion_hold'])
        fetched = self.call('proposal_discussion_get', {
            'proposal_id': 'proposal-1',
        })['structuredContent']
        self.assertEqual(fetched['workflow_discussion_version'], 3)

    def test_stdio_handshake_uses_json_lines_and_ignores_notifications(self):
        incoming = io.StringIO(
            json.dumps({'jsonrpc': '2.0', 'id': 7, 'method': 'initialize',
                        'params': {'protocolVersion': '2024-11-05', 'capabilities': {},
                                   'clientInfo': {'name': 'test', 'version': '1'}}}) + '\n' +
            json.dumps({'jsonrpc': '2.0', 'method': 'notifications/initialized'}) + '\n' +
            json.dumps({'jsonrpc': '2.0', 'id': 8, 'method': 'ping'}) + '\n')
        outgoing = io.StringIO()
        serve(self.worker, incoming, outgoing)
        messages = [json.loads(line) for line in outgoing.getvalue().splitlines()]
        self.assertEqual([message['id'] for message in messages], [7, 8])
        self.assertEqual(messages[0]['result']['protocolVersion'], '2024-11-05')
        self.assertEqual(messages[0]['result']['serverInfo']['name'],
                         'like-git-sharepoint-wiki-discussions')


if __name__ == '__main__':
    unittest.main()
