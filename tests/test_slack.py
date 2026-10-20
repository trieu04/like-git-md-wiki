import hashlib
import hmac
import json
import tempfile
import time
import unittest
from pathlib import Path

from wiki_worker.core import FixtureRemote, Worker
from wiki_worker.slack import SlackDiscussion, SlackError


class FakeSlack:
    def __init__(self):
        self.posts = []
        self.opened_topics = []
        self.fail_forward_once = False

    def open_topic(self, discussion_id, document_path, section_anchor, body,
                   resolve_assignees=None, decision_owners=None):
        self.opened_topics.append((discussion_id, document_path, section_anchor, body,
                                   resolve_assignees, decision_owners))
        return {'channel': 'C1', 'thread_ts': '100.1'}

    def post(self, thread, text):
        self.posts.append((thread, text))

    def close_topic(self, thread, discussion_id, outcome, reason, reviewer=None):
        self.posts.append((thread, 'closed ' + outcome))

    def notify_reviewer(self, thread, discussion_id, reviewer=None):
        self.posts.append((thread, 'notify'))

    def forward_decision(self, thread, discussion_id, actor, decision, reason,
                         reviewer=None, proposal_id=None):
        if self.fail_forward_once:
            self.fail_forward_once = False
            raise SlackError('temporary failure')
        self.posts.append((thread, ('forward', discussion_id, actor, decision, reason,
                                    reviewer, proposal_id)))


class SlackDiscussionTests(unittest.TestCase):
    def test_topic_root_lists_wiki_authors_as_advisory_mentions(self):
        slack = SlackDiscussion('token', 'C1')
        calls = []
        slack._call = lambda method, payload: (
            calls.append((method, payload)) or {'channel': 'C1', 'ts': '100.1'})

        slack.open_topic('d1', 'policy.md', 'deadline', 'Question',
                         ['policy-author', '@guide-author'],
                         ['guide-author', 'policy-author'])

        text = calls[0][1]['text']
        self.assertIn('Expected handlers (wiki authors, advisory only): '
                      '@policy-author @guide-author', text)
        self.assertIn('Decision representatives: @guide-author @policy-author', text)

    def test_failed_forward_is_retried_from_the_idempotent_request(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            remote = FixtureRemote(root / 'remote.sqlite')
            transport = FakeSlack()
            worker = Worker(root / 'state', remote, 'reviewer', slack=transport)
            self.addCleanup(remote.db.close); self.addCleanup(worker.db.close)
            ident = worker.create_topic('wiki', 'guide.md', 'intro', 'topic-1',
                                        'agent-reviewer', 'Human decision needed')
            event = {'type': 'app_mention', 'channel': 'C1', 'thread_ts': '100.1',
                     'user': 'Uhuman', 'ts': '100.2', 'text': '<@UBOT> reject needs evidence'}
            transport.fail_forward_once = True

            with self.assertRaises(SlackError):
                worker.handle_slack_event(event, 'Ureviewer')
            pending = worker.db.execute(
                'SELECT forwarded_at FROM reviewer_decision_requests').fetchone()
            self.assertIsNone(pending['forwarded_at'])

            retried = worker.handle_slack_event(event, 'Ureviewer')
            self.assertTrue(retried['forwarded'])
            self.assertEqual(retried['discussion_id'], ident)
            self.assertIsNotNone(worker.db.execute(
                'SELECT forwarded_at FROM reviewer_decision_requests').fetchone()['forwarded_at'])

    def test_app_mention_forwards_human_decision_without_reviewing(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            remote = FixtureRemote(root / 'remote.sqlite')
            transport = FakeSlack()
            worker = Worker(root / 'state', remote, 'reviewer', slack=transport)
            self.addCleanup(remote.db.close); self.addCleanup(worker.db.close)
            remote.write('guide.md', b'old\n', None)
            worker.propose('proposal-1', 'guide.md', b'new\n', 'author', 'Change')
            worker.create_topic('wiki', 'guide.md', 'intro', 'topic-1', 'agent-reviewer',
                                'Human decision needed', proposal_id='proposal-1')

            event = {'type': 'app_mention', 'channel': 'C1', 'thread_ts': '100.1',
                     'user': 'Uhuman', 'ts': '100.2',
                     'text': '<@UBOT> approve: policy owner confirmed'}
            result = worker.handle_slack_event(event, 'Ureviewer')

            self.assertEqual(result['decision'], 'approve')
            self.assertTrue(result['forwarded'])
            self.assertEqual(worker.row('proposal-1')['state'], 'pending')
            requests = worker.contribution('proposal-1')['reviewer_decision_requests']
            self.assertEqual([(r['actor'], r['decision'], r['reason']) for r in requests],
                             [('Uhuman', 'approve', 'policy owner confirmed')])
            self.assertEqual(worker.status()[0]['reviewer_decision_requests'][0]['decision'],
                             'approve')
            self.assertEqual(transport.posts[-1][1],
                             ('forward', result['discussion_id'], 'Uhuman', 'approve',
                              'policy owner confirmed', 'Ureviewer', 'proposal-1'))

            duplicate = worker.handle_slack_event(event, 'Ureviewer')
            self.assertTrue(duplicate['duplicate'])
            self.assertEqual(len(worker.contribution('proposal-1')['reviewer_decision_requests']), 1)
            self.assertEqual(worker.row('proposal-1')['state'], 'pending')

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
            ident = worker.create_topic('wiki', 'guide.md', 'intro', 'topic-1', 'U1', 'Question')
            topic = worker.discussion_topics()[0]
            result = worker.handle_slack_event({'type': 'message', 'channel': 'C1',
                                                'thread_ts': '100.1', 'user': 'U1',
                                                'ts': '100.2', 'text': 'close Evidence checked'}, 'Ureviewer')
            self.assertEqual(result['status'], 'resolved')
            self.assertEqual(worker.discussion_topics()[0]['status'], 'resolved')
            self.assertEqual(len(transport.posts), 2)
            self.assertEqual(topic['discussion_id'], ident)

    def test_head_conflict_does_not_automatically_open_slack_discussion(self):
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
            self.assertEqual(transport.opened_topics, [])
            self.assertEqual(worker.discussion_topics(topic_id='conflict-proposal-b'), [])


if __name__ == '__main__':
    unittest.main()
