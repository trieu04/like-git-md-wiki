import hashlib
import hmac
import json
import tempfile
import time
import unittest
from pathlib import Path

from wiki_worker.core import FixtureRemote, Worker
from wiki_worker.slack import SlackDiscussion


class FakeSlack:
    def __init__(self):
        self.posts = []
        self.opened_topics = []

    def open_topic(self, discussion_id, document_path, section_anchor, body):
        self.opened_topics.append((discussion_id, document_path, section_anchor, body))
        return {'channel': 'C1', 'thread_ts': '100.1'}

    def post(self, thread, text):
        self.posts.append((thread, text))

    def close_topic(self, thread, discussion_id, outcome, reason, reviewer=None):
        self.posts.append((thread, 'closed ' + outcome))

    def notify_reviewer(self, thread, discussion_id, reviewer=None):
        self.posts.append((thread, 'notify'))


class SlackDiscussionTests(unittest.TestCase):
    def test_signature_and_explicit_close_notify_reviewer(self):
        secret = 'secret'
        body = b'{"type":"url_verification","challenge":"ok"}'
        stamp = str(int(time.time()))
        digest = hmac.new(secret.encode(), b'v0:' + stamp.encode() + b':' + body, hashlib.sha256).hexdigest()
        self.assertTrue(SlackDiscussion.verify_signature(secret, stamp, body, 'v0=' + digest))

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            remote = FixtureRemote(root / 'remote.sqlite')
            transport = FakeSlack()
            worker = Worker(root / 'state', remote, 'reviewer', slack=transport)
            self.addCleanup(remote.db.close); self.addCleanup(worker.db.close)
            ident = worker.create_topic('wiki', 'guide.md', 'intro', 'topic-1', 'author', 'Question')
            topic = worker.discussion_topics()[0]
            result = worker.handle_slack_event({'type': 'message', 'channel': 'C1',
                                                'thread_ts': '100.1', 'user': 'U1',
                                                'ts': '100.2', 'text': 'close Evidence checked'}, 'Ureviewer')
            self.assertEqual(result['status'], 'resolved')
            self.assertEqual(worker.discussion_topics()[0]['status'], 'resolved')
            self.assertEqual(len(transport.posts), 2)
            self.assertEqual(topic['discussion_id'], ident)

    def test_head_conflict_opens_one_slack_discussion(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            remote = FixtureRemote(root / 'remote.sqlite')
            transport = FakeSlack()
            worker = Worker(root / 'state', remote, 'reviewer', slack=transport)
            self.addCleanup(remote.db.close); self.addCleanup(worker.db.close)

            remote.write('page.md', b'v1\n', None)
            for ident, content in (('proposal-a', b'v1\nA\n'), ('proposal-b', b'v1\nB\n')):
                proposal = root / ident
                proposal.mkdir()
                (proposal / 'base.md').write_bytes(b'v1\n')
                (proposal / 'proposed.md').write_bytes(content)
                (proposal / 'proposal.ready.json').write_text(json.dumps({
                    'schema_version': 1, 'id': ident, 'target': 'page.md',
                    'base_hash': hashlib.sha256(b'v1\n').hexdigest(),
                    'proposed_hash': hashlib.sha256(content).hexdigest(),
                    'reason': 'Concurrent edit', 'sources': []}))
                worker.scan(proposal, 'author')
                preview = worker.preview(ident, 'reviewer')
                worker.review(ident, 'reviewer', preview, True, 'Checked')

            self.assertEqual(worker.publish('proposal-a'), 'published')
            self.assertEqual(worker.publish('proposal-b'), 'stale')
            self.assertIsNotNone(worker.contribution('proposal-b')['conflict'])
            self.assertEqual(len(transport.opened_topics), 1)
            opened = transport.opened_topics[0]
            self.assertEqual(opened[:3], ('conflict-proposal-b', 'page.md', 'conflict'))
            topic = worker.discussion_topics(topic_id='conflict-proposal-b')[0]
            self.assertEqual(topic['slack_channel'], 'C1')
            self.assertEqual(topic['slack_thread_ts'], '100.1')


if __name__ == '__main__':
    unittest.main()
