"""Slack-backed discussion transport.

Discussion text lives in Slack threads. The worker stores only the proposal
binding and Slack thread coordinates so it can re-read the conversation.
"""
import json
import hashlib
import hmac
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class SlackError(RuntimeError):
    pass


class SlackDiscussion:
    def __init__(self, token, channel, timeout=15):
        self.token, self.channel, self.timeout = token, channel, timeout

    def _call(self, method, payload):
        request = Request('https://slack.com/api/' + method,
                          data=urlencode(payload).encode(),
                          headers={'Authorization': 'Bearer ' + self.token,
                                   'Content-Type': 'application/x-www-form-urlencoded'})
        with urlopen(request, timeout=self.timeout) as response:
            result = json.loads(response.read())
        if not result.get('ok'):
            raise SlackError(result.get('error', 'Slack API request failed'))
        return result

    def open(self, proposal_id, bundle_hash, reason):
        result = self._call('chat.postMessage', {'channel': self.channel,
            'text': f'Wiki discussion `{proposal_id}` opened\nBundle: `{bundle_hash}`\n{reason}'})
        return {'channel': result['channel'], 'thread_ts': result['ts']}

    def open_topic(self, discussion_id, document_path, section_anchor, body,
                   resolve_assignees=None, decision_owners=None):
        authors = ' '.join('@' + author.lstrip('@') for author in (resolve_assignees or []))
        responsibility = ''
        if authors:
            representatives = ' '.join(
                '@' + owner.lstrip('@') for owner in (decision_owners or []))
            responsibility = (f'\nExpected handlers (wiki authors, advisory only): {authors}'
                              f'\nDecision representatives: {representatives}')
        result = self._call('chat.postMessage', {'channel': self.channel,
            'text': (f'Wiki discussion `{discussion_id}` opened\n'
                     f'File: `{document_path}` · Section: `{section_anchor}`'
                     f'{responsibility}\n{body}')})
        return {'channel': result['channel'], 'thread_ts': result['ts']}

    def post(self, thread, text):
        self._call('chat.postMessage', {'channel': thread['channel'],
                                        'thread_ts': thread['thread_ts'], 'text': text})

    def messages(self, thread):
        result = self._call('conversations.replies', {'channel': thread['channel'],
                                                       'ts': thread['thread_ts'], 'limit': 200})
        return result.get('messages', [])

    def close_topic(self, thread, discussion_id, outcome, reason, reviewer=None):
        mention = f' <@{reviewer}>' if reviewer else ''
        self.post(thread, f'Wiki discussion `{discussion_id}` closed: *{outcome}*{mention}\n{reason}')

    def notify_reviewer(self, thread, discussion_id, reviewer=None):
        mention = f'<@{reviewer}> ' if reviewer else ''
        self.post(thread, f'{mention}Discussion `{discussion_id}` is ready for reviewer decision.')

    def forward_decision(self, thread, discussion_id, actor, decision, reason,
                         reviewer=None, proposal_id=None):
        """Forward a human decision request without applying it to a proposal."""
        mention = f'<@{reviewer}> ' if reviewer else ''
        proposal = f' for proposal `{proposal_id}`' if proposal_id else ''
        self.post(
            thread,
            f'{mention}Human decision from <@{actor}>{proposal}: *{decision}*\n'
            f'Discussion: `{discussion_id}`\nReason: {reason}')

    @staticmethod
    def verify_signature(signing_secret, timestamp, body, signature, max_age=300):
        try:
            if abs(time.time() - int(timestamp)) > max_age:
                return False
        except (TypeError, ValueError):
            return False
        digest = hmac.new(signing_secret.encode(),
                          f'v0:{timestamp}:'.encode() + body,
                          hashlib.sha256).hexdigest()
        return hmac.compare_digest(signature or '', 'v0=' + digest)
