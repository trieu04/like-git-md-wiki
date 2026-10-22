import json
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from wiki_worker.core import FixtureRemote, Worker
from wiki_worker.teams import TeamsDiscussion, TeamsError
from wiki_worker.web import Application, Handler


class RecordingTeams(TeamsDiscussion):
    def __init__(self):
        super().__init__('token', 'team-1', 'channel-1')
        self.calls = []

    def _call(self, method, path, payload=None):
        self.calls.append((method, path, payload))
        if method == 'POST' and path.endswith('/messages'):
            return {'id': 'root-1'}
        if method == 'POST':
            return {'id': 'reply-from-worker'}
        raise AssertionError((method, path, payload))


class TeamsDiscussionTests(unittest.TestCase):
    def test_open_topic_and_reply_use_graph_channel_thread(self):
        teams = RecordingTeams()

        thread = teams.open_topic('discussion-1', 'policy.md', 'deadline', 'Question',
                                  ['policy-author'], ['policy-owner'])
        teams.post(thread, 'Evidence checked')

        self.assertEqual(thread, {'team': 'team-1', 'channel': 'channel-1',
                                  'thread_ts': 'root-1'})
        method, path, payload = teams.calls[0]
        self.assertEqual((method, path),
                         ('POST', '/teams/team-1/channels/channel-1/messages'))
        self.assertEqual(payload['body']['contentType'], 'text')
        self.assertIn('Expected handlers (wiki authors, advisory only): @policy-author',
                      payload['body']['content'])
        self.assertEqual(teams.calls[1][1],
                         '/teams/team-1/channels/channel-1/messages/root-1/replies')

    def test_messages_include_root_and_follow_graph_pagination(self):
        teams = TeamsDiscussion('token', 'team', 'channel')
        calls = []

        def call(method, path, payload=None):
            calls.append((method, path))
            if path.endswith('/messages/root'):
                return {'id': 'root', 'body': {'content': '<p>Root</p>'},
                        'from': {'user': {'id': 'owner'}}}
            if path.endswith('/replies'):
                return {'value': [{'id': 'reply-1', 'replyToId': 'root',
                                   'body': {'content': '<div>First<br>reply</div>'},
                                   'from': {'user': {'id': 'u1'}}}],
                        '@odata.nextLink': 'https://graph.microsoft.com/v1.0/next'}
            if path == 'https://graph.microsoft.com/v1.0/next':
                return {'value': [{'id': 'reply-2', 'replyToId': 'root',
                                   'body': {'content': 'Second'},
                                   'from': {'user': {'displayName': 'User Two'}}}]}
            raise AssertionError(path)

        teams._call = call
        messages = teams.messages({'channel': 'channel', 'thread_ts': 'root'})

        self.assertEqual([message['ts'] for message in messages],
                         ['root', 'reply-1', 'reply-2'])
        self.assertEqual(messages[1]['text'], 'First\nreply')
        self.assertEqual(messages[2]['user'], 'User Two')
        self.assertEqual(calls[-1][1], 'https://graph.microsoft.com/v1.0/next')

    def test_rejects_continuation_url_that_could_leak_token(self):
        teams = TeamsDiscussion('token', 'team', 'channel')
        with self.assertRaises(TeamsError):
            teams._request_url('https://example.test/steal-token')

    def test_notification_fetch_is_limited_to_configured_channel(self):
        teams = TeamsDiscussion('token', 'team', 'channel')
        with self.assertRaises(TeamsError):
            teams.notification_message({
                'changeType': 'created',
                'resource': "teams('another-team')/channels('channel')/messages('1')",
                'resourceData': {'id': '1'},
            })

        teams._call = lambda method, path, payload=None: {
            'id': 'reply', 'replyToId': 'root',
            'channelIdentity': {'channelId': 'channel'},
            'from': {'user': {'id': 'human'}},
            'body': {'content': 'Evidence'},
        }
        event = teams.notification_message({
            'changeType': 'created',
            'resource': "teams('team')/channels('channel')/messages('reply')",
            'resourceData': {'id': 'reply'},
        })
        self.assertEqual((event['thread_ts'], event['text']), ('root', 'Evidence'))

    def test_graph_notification_forwards_decision_without_reviewing(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            remote = FixtureRemote(root / 'remote.sqlite')
            teams = RecordingTeams()
            worker = Worker(root / 'state', remote, 'reviewer', slack=teams)
            try:
                remote.write('guide.md', b'old\n', None)
                worker.propose('proposal-1', 'guide.md', b'new\n', 'author', 'Change')
                worker.create_topic('wiki', 'guide.md', 'intro', 'topic-1', 'agent',
                                    'Human decision needed', proposal_id='proposal-1')

                result = worker.handle_teams_event({
                    'changeType': 'created',
                    'resourceData': {
                        'id': 'reply-1', 'replyToId': 'root-1',
                        'channelIdentity': {'channelId': 'channel-1'},
                        'from': {'user': {'id': 'human-1'}},
                        'body': {'contentType': 'html',
                                 'content': '<p>approve: owner confirmed</p>'},
                    },
                }, 'reviewer-user')

                self.assertTrue(result['forwarded'])
                self.assertEqual(result['decision'], 'approve')
                self.assertEqual(worker.row('proposal-1')['state'], 'pending')
                request = worker.contribution('proposal-1')['reviewer_decision_requests'][0]
                self.assertEqual((request['actor'], request['reason']),
                                 ('human-1', 'owner confirmed'))
                self.assertTrue(teams.calls[-1][1].endswith('/messages/root-1/replies'))
                payload = teams.calls[-1][2]
                self.assertIn('<at id="0">reviewer-user</at>', payload['body']['content'])
                self.assertEqual(payload['mentions'][0]['mentioned']['user']['id'],
                                 'reviewer-user')
            finally:
                worker.db.close()
                remote.db.close()

    def test_close_does_not_require_resolver_to_match_wiki_author(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            remote = FixtureRemote(root / 'remote.sqlite')
            teams = RecordingTeams()
            worker = Worker(root / 'state', remote, 'reviewer', slack=teams)
            try:
                remote.write('guide.md', b'old\n', None)
                worker.propose('proposal-1', 'guide.md', b'new\n',
                               'wiki-author', 'Change')
                worker.create_topic(
                    'wiki', 'guide.md', 'intro', 'topic-1', 'facilitator',
                    'Human decision needed', proposal_id='proposal-1',
                    decision_owners=['expected-owner'])

                result = worker.handle_teams_event({
                    'changeType': 'created',
                    'resourceData': {
                        'id': 'reply-1', 'replyToId': 'root-1',
                        'channelIdentity': {'channelId': 'channel-1'},
                        'from': {'user': {'id': 'another-teams-user'}},
                        'body': {'contentType': 'text',
                                 'content': 'close Evidence checked'},
                    },
                }, 'reviewer-user')

                self.assertEqual(result['status'], 'resolved')
                self.assertEqual(worker.discussion_topics()[0]['status'], 'resolved')
                self.assertEqual(worker.row('proposal-1')['state'], 'pending')
            finally:
                worker.db.close()
                remote.db.close()


class TeamsWebhookTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        wiki = root / 'wiki'
        wiki.mkdir()
        (wiki / 'index.md').write_text('# Wiki\n')
        self.teams = RecordingTeams()
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.application = Application(root / 'state', wiki, None,
                                              'reviewer', 'Owner', self.teams,
                                              teams_client_state='state-secret')
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.base = f'http://127.0.0.1:{self.server.server_port}'

    def test_validation_token_is_returned_as_plain_text(self):
        request = urllib.request.Request(
            self.base + '/api/teams/events?validationToken=opaque%20token',
            data=b'', method='POST')
        with urllib.request.urlopen(request) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.headers.get_content_type(), 'text/plain')
            self.assertEqual(response.read(), b'opaque token')

    def test_notifications_require_matching_client_state(self):
        payload = json.dumps({'value': [
            {'clientState': 'wrong', 'changeType': 'created',
             'resourceData': {'id': 'message'}}]}).encode()
        request = urllib.request.Request(
            self.base + '/api/teams/events', data=payload, method='POST',
            headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(request) as response:
            result = json.loads(response.read())
            self.assertEqual(response.status, 202)
            self.assertEqual(result, {'accepted': 0, 'ignored': 1, 'results': []})


if __name__ == '__main__':
    unittest.main()
