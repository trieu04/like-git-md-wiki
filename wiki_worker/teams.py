"""Microsoft Teams discussion transport backed by Microsoft Graph.

The adapter deliberately accepts an already-issued access token. Token
acquisition and refresh belong to the trusted host process; keeping them out of
the worker avoids storing Microsoft identity credentials in wiki state.
"""
from html import escape, unescape
from html.parser import HTMLParser
import json
import hmac
import re
from urllib.error import HTTPError
from urllib.parse import quote, unquote, urlsplit
from urllib.request import Request, urlopen


class TeamsError(RuntimeError):
    pass


class _TeamsText(HTMLParser):
    """Turn the small HTML subset used by Teams messages into plain text."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in ('br', 'p', 'div', 'li') and self.parts:
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if tag in ('p', 'div', 'li'):
            self.parts.append('\n')

    def handle_data(self, data):
        self.parts.append(data)

    def text(self):
        return re.sub(r'\n{3,}', '\n\n', ''.join(self.parts)).strip()


def _plain_text(content):
    parser = _TeamsText()
    parser.feed(content or '')
    parser.close()
    return unescape(parser.text())


class TeamsDiscussion:
    """Mirror wiki discussions to one Microsoft Teams channel.

    ``token`` must be a Microsoft Graph access token. Sending normal channel
    messages requires delegated ``ChannelMessage.Send`` permission. Reading
    replies requires an appropriate channel-message read permission.
    """

    graph_url = 'https://graph.microsoft.com/v1.0'

    def __init__(self, token, team, channel, timeout=15):
        if not all(isinstance(value, str) and value.strip()
                   for value in (token, team, channel)):
            raise TeamsError('Teams token, team and channel are required')
        self.token, self.team, self.channel, self.timeout = (
            token.strip(), team.strip(), channel.strip(), timeout)

    @staticmethod
    def _segment(value):
        return quote(value, safe='')

    def _channel_path(self):
        return (f'/teams/{self._segment(self.team)}/channels/'
                f'{self._segment(self.channel)}/messages')

    def _request_url(self, path):
        if path.startswith('https://'):
            parsed = urlsplit(path)
            graph = urlsplit(self.graph_url)
            if parsed.scheme != graph.scheme or parsed.netloc != graph.netloc:
                raise TeamsError('refusing a Microsoft Graph continuation URL on another host')
            return path
        path = '/' + path.lstrip('/')
        if path.startswith('/v1.0/'):
            path = path[len('/v1.0'):]
        return self.graph_url + path

    def _call(self, method, path, payload=None):
        data = None if payload is None else json.dumps(payload).encode()
        headers = {'Authorization': 'Bearer ' + self.token,
                   'Accept': 'application/json'}
        if data is not None:
            headers['Content-Type'] = 'application/json'
        request = Request(self._request_url(path), data=data, headers=headers,
                          method=method)
        try:
            with urlopen(request, timeout=self.timeout) as response:
                raw = response.read()
        except HTTPError as exc:
            raw = exc.read()
            message = f'Microsoft Graph request failed ({exc.code})'
            try:
                error = json.loads(raw).get('error', {})
                message = error.get('message') or error.get('code') or message
            except (UnicodeError, ValueError, AttributeError):
                pass
            raise TeamsError(message) from exc
        if not raw:
            return {}
        try:
            result = json.loads(raw)
        except (UnicodeError, ValueError) as exc:
            raise TeamsError('Microsoft Graph returned invalid JSON') from exc
        if not isinstance(result, dict):
            raise TeamsError('Microsoft Graph returned an invalid response')
        return result

    @staticmethod
    def _body(text, mention=None):
        if not mention:
            return {'body': {'contentType': 'text', 'content': text}}
        label = mention.lstrip('@')
        content = escape(text).replace('\n', '<br>')
        return {
            'body': {'contentType': 'html',
                     'content': f'<at id="0">{escape(label)}</at> {content}'},
            'mentions': [{
                'id': 0,
                'mentionText': label,
                'mentioned': {'user': {'id': label, 'displayName': label,
                                       'userIdentityType': 'aadUser'}},
            }],
        }

    @staticmethod
    def _thread(channel, message_id, team=None):
        # ``channel``/``thread_ts`` is the worker's legacy transport-neutral
        # coordinate shape. Teams maps the root message ID to the thread key.
        return {'team': team, 'channel': channel, 'thread_ts': message_id}

    def open(self, proposal_id, bundle_hash, reason):
        result = self._call('POST', self._channel_path(), self._body(
            f'Wiki discussion `{proposal_id}` opened\n'
            f'Bundle: `{bundle_hash}`\n{reason}'))
        if not result.get('id'):
            raise TeamsError('Microsoft Graph did not return a message ID')
        return self._thread(self.channel, result['id'], self.team)

    def open_topic(self, discussion_id, document_path, section_anchor, body,
                   resolve_assignees=None, decision_owners=None):
        authors = ' '.join('@' + author.lstrip('@')
                           for author in (resolve_assignees or []))
        responsibility = ''
        if authors:
            representatives = ' '.join('@' + owner.lstrip('@')
                                       for owner in (decision_owners or []))
            responsibility = (f'\nExpected handlers (wiki authors, advisory only): {authors}'
                              f'\nDecision representatives: {representatives}')
        result = self._call('POST', self._channel_path(), self._body(
            f'Wiki discussion `{discussion_id}` opened\n'
            f'File: `{document_path}` · Section: `{section_anchor}`'
            f'{responsibility}\n{body}'))
        if not result.get('id'):
            raise TeamsError('Microsoft Graph did not return a message ID')
        return self._thread(self.channel, result['id'], self.team)

    def _message_path(self, thread):
        channel = thread.get('channel') or self.channel
        message_id = thread.get('thread_ts') or thread.get('message_id')
        if not message_id:
            raise TeamsError('Teams thread message ID is required')
        return (f'/teams/{self._segment(thread.get("team") or self.team)}/channels/'
                f'{self._segment(channel)}/messages/{self._segment(message_id)}')

    def post(self, thread, text, mention=None):
        self._call('POST', self._message_path(thread) + '/replies',
                   self._body(text, mention))

    @staticmethod
    def _actor(message):
        sender = message.get('from') or {}
        principal = sender.get('user') or sender.get('application') or sender.get('device') or {}
        return principal.get('id') or principal.get('displayName') or 'teams-user'

    def _normalize(self, message, channel=None):
        if not isinstance(message, dict):
            return None
        body = message.get('body') or {}
        normalized = {
            'type': 'app_mention',
            'channel': channel or (message.get('channelIdentity') or {}).get('channelId')
                       or self.channel,
            'thread_ts': message.get('replyToId'),
            'user': self._actor(message),
            'ts': message.get('id'),
            'text': _plain_text(body.get('content', '')),
        }
        sender = message.get('from') or {}
        if sender.get('application') and not sender.get('user'):
            normalized['bot_id'] = normalized['user']
        return normalized

    def messages(self, thread):
        """Return the root plus all replies in Slack-compatible order."""
        path = self._message_path(thread)
        root = self._call('GET', path)
        result = [self._normalize(root, thread.get('channel') or self.channel)]
        page = self._call('GET', path + '/replies')
        while True:
            result.extend(self._normalize(item, thread.get('channel') or self.channel)
                          for item in page.get('value', []))
            next_link = page.get('@odata.nextLink')
            if not next_link:
                break
            page = self._call('GET', next_link)
        return [item for item in result if item is not None]

    def notification_message(self, notification):
        """Fetch and normalize one Microsoft Graph chatMessage notification."""
        if not isinstance(notification, dict) or notification.get('changeType') not in (None, 'created'):
            return None
        data = notification.get('resourceData') or {}
        message = data if isinstance(data.get('body'), dict) else None
        if message is None:
            resource = notification.get('resource') or data.get('@odata.id')
            if not isinstance(resource, str) or not resource.strip():
                raise TeamsError('Teams notification does not identify a message')
            parsed = urlsplit(resource)
            path = unquote(parsed.path if parsed.scheme else resource).lstrip('/')
            if path.startswith('v1.0/'):
                path = path[len('v1.0/'):]
            rest_prefix = f'teams/{self.team}/channels/{self.channel}/messages/'
            odata_prefix = f"teams('{self.team}')/channels('{self.channel}')/messages("
            if not (path.startswith(rest_prefix) or path.startswith(odata_prefix)):
                raise TeamsError('Teams notification is outside the configured channel')
            message = self._call('GET', resource)
        return self._normalize(message)

    @staticmethod
    def verify_notification(client_state, notification):
        return (isinstance(notification, dict) and isinstance(client_state, str) and
                hmac.compare_digest(notification.get('clientState') or '', client_state))

    def close_topic(self, thread, discussion_id, outcome, reason, reviewer=None):
        self.post(thread, f'Wiki discussion `{discussion_id}` closed: {outcome}\n{reason}',
                  reviewer)

    def notify_reviewer(self, thread, discussion_id, reviewer=None):
        self.post(thread, f'Discussion `{discussion_id}` is ready for reviewer decision.',
                  reviewer)

    def forward_decision(self, thread, discussion_id, actor, decision, reason,
                         reviewer=None, proposal_id=None):
        proposal = f' for proposal `{proposal_id}`' if proposal_id else ''
        self.post(thread,
                  f'Human decision from @{actor}{proposal}: {decision}\n'
                  f'Discussion: `{discussion_id}`\nReason: {reason}', reviewer)
