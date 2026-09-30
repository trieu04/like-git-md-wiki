"""Local reviewer UI; contributions arrive as files, not author API calls."""
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from urllib.parse import parse_qs, unquote, urlsplit
import json

from .common import Conflict, Invalid, LIMIT, target_path
from .core import Worker
from .fixture import FixtureRemote
from .local import LocalFolderStorage
from .skill import describe, skill_file
from .slack import SlackError


class Application:
    def __init__(self, state, folder, fixture, reviewer, owner, slack=None, slack_signing_secret=None, slack_reviewer=None):
        self.state, self.folder, self.fixture = state, folder, fixture
        self.reviewer, self.owner, self.slack = reviewer, owner, slack
        self.slack_signing_secret, self.slack_reviewer = slack_signing_secret, slack_reviewer
        self.index = files('wiki_worker').joinpath('static/index.html').read_bytes()

    def worker(self):
        storage = LocalFolderStorage(self.folder) if self.folder else FixtureRemote(self.fixture)
        return Worker(self.state, storage, self.reviewer, self.owner, slack=self.slack)

    def close(self, worker):
        worker.db.close()
        database = getattr(worker.remote, 'db', None)
        if database is not None:
            database.close()


class Handler(BaseHTTPRequestHandler):
    server_version = 'WikiLayer/0.2'

    def json(self, status, value):
        payload = json.dumps(value, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(payload)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(payload)

    def body(self):
        try:
            length = int(self.headers.get('Content-Length', '0'))
        except ValueError as exc:
            raise Invalid('invalid Content-Length') from exc
        if length <= 0 or length > 8 * LIMIT + 65536:
            raise Invalid('request body is empty or too large')
        try:
            value = json.loads(self.rfile.read(length))
        except (UnicodeError, ValueError) as exc:
            raise Invalid('request body must be valid JSON') from exc
        if not isinstance(value, dict):
            raise Invalid('request body must be an object')
        return value

    def do_GET(self):
        worker = None
        try:
            route = urlsplit(self.path).path
            if route == '/app.js':
                payload = files('wiki_worker').joinpath('static/app.js').read_bytes()
                self.send_response(HTTPStatus.OK)
                self.send_header('Content-Type', 'text/javascript; charset=utf-8')
                self.send_header('Content-Length', str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return
            if route == '/':
                payload = self.server.application.index
                self.send_response(HTTPStatus.OK)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Content-Length', str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return
            if route == '/api/skill':
                return self.json(HTTPStatus.OK, describe())
            if route in ('/api/skill/contributor', '/api/skill/reviewer'):
                role = route.rsplit('/', 1)[1]
                filename, payload = skill_file(role)
                self.send_response(HTTPStatus.OK)
                self.send_header('Content-Type', 'text/markdown; charset=utf-8')
                self.send_header('Content-Disposition', f'attachment; filename="{filename}"')
                self.send_header('Content-Length', str(len(payload)))
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                self.wfile.write(payload)
                return
            worker = self.server.application.worker()
            if route == '/api/config':
                return self.json(HTTPStatus.OK, dict(reviewer=worker.reviewer, owner=worker.owner,
                    storage='local folder' if self.server.application.folder else 'fixture'))
            if route == '/api/contribution':
                return self.json(HTTPStatus.OK, worker.status())
            if route == '/api/discussions':
                query = parse_qs(urlsplit(self.path).query)
                return self.json(HTTPStatus.OK, worker.discussion_topics(
                    query.get('project_id', [None])[0], query.get('document_path', [None])[0],
                    query.get('section_anchor', [None])[0], query.get('topic_id', [None])[0]))
            if len(parts := route.strip('/').split('/')) == 3 and parts[:2] == ['api', 'discussions']:
                topics = worker.discussion_topics()
                match = [item for item in topics if item['discussion_id'] == unquote(parts[2])]
                if not match:
                    return self.json(HTTPStatus.NOT_FOUND, {'error': 'discussion not found'})
                return self.json(HTTPStatus.OK, match[0])
            if route == '/api/wiki':
                return self.json(HTTPStatus.OK, worker.remote.list_markdown())
            if route in ('/api/wiki/versions', '/api/wiki/version'):
                query = parse_qs(urlsplit(self.path).query)
                path = target_path(query.get('path', [''])[0])
                version = query.get('version', [''])[0] if route == '/api/wiki/version' else None
                return self.json(HTTPStatus.OK, worker.document_history(path, version))
            if route == '/api/wiki/document':
                query = parse_qs(urlsplit(self.path).query)
                path = target_path(query.get('path', [''])[0])
                captured = worker.agent_context(path, [])
                document = captured['documents'][0]
                if document['content'] is None:
                    return self.json(HTTPStatus.NOT_FOUND, {'error': 'document not found'})
                return self.json(HTTPStatus.OK, {'path': path, 'content': document['content'],
                                                 'reference': captured['context']['target']})
            parts = route.strip('/').split('/')
            if len(parts) == 3 and parts[:2] == ['api', 'contribution']:
                return self.json(HTTPStatus.OK, worker.contribution(unquote(parts[2])))
            if len(parts) == 3 and parts[:2] == ['api', 'discussion']:
                return self.json(HTTPStatus.OK, worker.get_discussion(unquote(parts[2])))
            self.json(HTTPStatus.NOT_FOUND, {'error': 'route not found'})
        except (Invalid, Conflict, SlackError, UnicodeError, ValueError) as exc:
            self.json(HTTPStatus.BAD_REQUEST, {'error': str(exc)})
        finally:
            if worker is not None:
                self.server.application.close(worker)

    def do_POST(self):
        worker = None
        try:
            route = urlsplit(self.path).path
            parts = route.strip('/').split('/')
            if route == '/api/slack/events':
                raw = self.rfile.read(int(self.headers.get('Content-Length', '0')))
                slack = self.server.application.slack
                secret = self.server.application.slack_signing_secret
                if slack is None or not secret or not slack.verify_signature(secret,
                        self.headers.get('X-Slack-Request-Timestamp'), raw,
                        self.headers.get('X-Slack-Signature')):
                    return self.json(HTTPStatus.UNAUTHORIZED, {'error': 'invalid Slack signature'})
                data = json.loads(raw)
                if data.get('type') == 'url_verification':
                    return self.json(HTTPStatus.OK, {'challenge': data.get('challenge')})
                worker = self.server.application.worker()
                result = worker.handle_slack_event(data.get('event', data), self.server.application.slack_reviewer)
                return self.json(HTTPStatus.OK, result)
            discussion_route = (route in ('/api/discussion', '/api/discussions') or
                (len(parts) == 4 and parts[:2] == ['api', 'discussion'] and
                 parts[3] in ('messages', 'resolve', 'hold', 'sync')) or
                (len(parts) == 4 and parts[:2] == ['api', 'discussions'] and parts[3] in ('comments', 'close')) or
                route == '/api/slack/events')
            if (route != '/api/contribution/import' and not discussion_route and not
                    (len(parts) == 4 and parts[:2] == ['api', 'contribution'] and
                     parts[3] in ('review', 'publish', 'discussion', 'conflict', 'concurrent-discussion', 'rollback'))):
                return self.json(HTTPStatus.NOT_FOUND, {'error': 'route not found'})
            data = self.body()
            worker = self.server.application.worker()
            if len(parts) == 4 and parts[:2] == ['api', 'discussions'] and parts[3] == 'comments':
                required = ('author', 'body', 'topic_id', 'section_anchor')
                if any(not isinstance(data.get(k), str) for k in required):
                    raise Invalid('incomplete discussion comment')
                comment_id = worker.add_discussion_comment(
                    unquote(parts[2]), data['author'], data['body'], data['topic_id'],
                    data['section_anchor'], data.get('proposal_id'), data.get('parent_comment_id'),
                    data.get('status', 'open'), data.get('source_ref'))
                return self.json(HTTPStatus.CREATED, {'comment_id': comment_id})
            if len(parts) == 4 and parts[:2] == ['api', 'discussions'] and parts[3] == 'close':
                required = ('actor', 'outcome', 'reason')
                if any(not isinstance(data.get(k), str) for k in required):
                    raise Invalid('incomplete discussion close')
                return self.json(HTTPStatus.OK, worker.close_topic(
                    unquote(parts[2]), data['actor'], data['outcome'], data['reason'],
                    data.get('reviewer')))
            if route == '/api/discussions':
                required = ('project_id', 'document_path', 'section_anchor', 'topic_id', 'author', 'body')
                if any(not isinstance(data.get(k), str) for k in required):
                    raise Invalid('incomplete topic discussion')
                ident = worker.create_topic(data['project_id'], data['document_path'], data['section_anchor'],
                                            data['topic_id'], data['author'], data['body'],
                                            data.get('parent_topic_id'), data.get('proposal_id'),
                                            data.get('source_refs'), data.get('status', 'open'), data.get('discussion_id'))
                return self.json(HTTPStatus.CREATED, {'discussion_id': ident})
            if route == '/api/contribution/import':
                if not isinstance(data.get('file'), str) or not isinstance(data.get('submitter'), str) or not data['submitter'].strip():
                    raise Invalid('contribution file and verified submitter required')
                ident = worker.import_contribution(data['file'].encode(), data['submitter'])
                return self.json(HTTPStatus.CREATED, {'id': ident})
            if route == '/api/discussion':
                required = ('proposal_id', 'actor', 'bundle_hash', 'reason')
                if any(not isinstance(data.get(key), str) for key in required):
                    raise Invalid('incomplete discussion creation')
                result = worker.create_discussion(data['proposal_id'], data['actor'],
                                                  data['bundle_hash'], data['reason'])
                return self.json(HTTPStatus.CREATED, result)
            if len(parts) == 4 and parts[:2] == ['api', 'discussion']:
                ident = unquote(parts[2])
                if parts[3] == 'sync':
                    sync = worker.sync_discord_discussion if worker.slack.__class__.__name__ == 'DiscordDiscussion' else worker.sync_slack_discussion
                    return self.json(HTTPStatus.OK, sync(ident))
                required = ('actor', 'bundle_hash', 'discussion_version')
                if (any(key not in data for key in required) or
                        not isinstance(data.get('actor'), str) or not isinstance(data.get('bundle_hash'), str) or
                        type(data.get('discussion_version')) is not int):
                    raise Invalid('incomplete discussion request')
                if parts[3] == 'messages':
                    if not isinstance(data.get('message'), str):
                        raise Invalid('discussion message required')
                    result = worker.add_discussion_message(
                        ident, data['actor'], data['bundle_hash'], data['discussion_version'],
                        data['message'], data.get('agrees_with'))
                elif parts[3] == 'hold':
                    if not isinstance(data.get('reason'), str):
                        raise Invalid('hold reason required')
                    result = worker.hold_proposal(ident, data['actor'], data['bundle_hash'],
                                                  data['discussion_version'], data['reason'])
                else:
                    if not isinstance(data.get('decision'), str) or not isinstance(data.get('reason'), str):
                        raise Invalid('discussion decision and reason required')
                    result = worker.resolve_discussion(ident, data['actor'], data['bundle_hash'],
                                                       data['discussion_version'], data['decision'], data['reason'])
                return self.json(HTTPStatus.OK, result)
            ident = unquote(parts[2])
            if parts[3] == 'discussion':
                keys = ('actor', 'bundle_hash', 'action', 'reason')
                if any(not isinstance(data.get(key), str) for key in keys):
                    raise Invalid('incomplete semantic discussion entry')
                result = worker.discuss(
                    ident, data['actor'], data['bundle_hash'], data.get('discussion_version'),
                    data['action'], data['reason'], data.get('resolution_kind'),
                    data.get('related_contribution_ids'))
                return self.json(HTTPStatus.OK, result)
            if parts[3] == 'conflict':
                required = ('actor', 'outcome', 'reason')
                if any(not isinstance(data.get(key), str) for key in required):
                    raise Invalid('incomplete conflict resolution')
                result = worker.resolve_conflict(unquote(parts[2]), data['actor'], data['outcome'],
                                                 data['reason'], data.get('merged_content'))
                return self.json(HTTPStatus.OK, result)
            if parts[3] == 'concurrent-discussion':
                if not all(isinstance(data.get(key), str) and data[key].strip()
                           for key in ('actor', 'section_anchor', 'reason')):
                    raise Invalid('incomplete concurrent discussion request')
                result = worker.open_concurrent_discussion(
                    unquote(parts[2]), data['actor'], data['section_anchor'],
                    data['reason'], data.get('related_proposal_ids'), data.get('project_id', 'wiki'))
                return self.json(HTTPStatus.CREATED, result)
            if parts[3] == 'rollback':
                if not all(isinstance(data.get(key), str) and data[key].strip()
                           for key in ('actor', 'reason')):
                    raise Invalid('incomplete rollback request')
                return self.json(HTTPStatus.OK, worker.rollback_to_base(
                    unquote(parts[2]), data['actor'], data['reason'], data.get('expected_v2_hash')))
            if parts[3] == 'review':
                keys = ('bundle_hash', 'time', 'artifact', 'actor', 'reason')
                if any(not isinstance(data.get(k), str) for k in keys) or not isinstance(data.get('approve'), bool):
                    raise Invalid('incomplete review decision')
                preview = dict(bundle_hash=data['bundle_hash'], time=data['time'],
                               artifact=data['artifact'].encode(),
                               discussion_version=data.get('discussion_version'),
                               workflow_discussion_version=data.get('workflow_discussion_version'))
                worker.review(ident, data['actor'], preview, data['approve'], data['reason'])
                return self.json(HTTPStatus.OK, {'state': 'approved' if data['approve'] else 'rejected'})
            return self.json(HTTPStatus.OK, {'state': worker.publish(ident)})
        except (Invalid, Conflict, SlackError, UnicodeError) as exc:
            self.json(HTTPStatus.BAD_REQUEST, {'error': str(exc)})
        finally:
            if worker is not None:
                self.server.application.close(worker)

    def log_message(self, pattern, *args):
        print('%s - %s' % (self.address_string(), pattern % args))


def serve(host, port, state, folder, fixture, reviewer, owner, slack=None,
          slack_signing_secret=None, slack_reviewer=None):
    if host not in ('127.0.0.1', '::1', 'localhost'):
        raise Invalid('web UI currently binds to localhost only; authentication is not implemented')
    server = ThreadingHTTPServer((host, port), Handler)
    server.application = Application(state, folder, fixture, reviewer, owner, slack,
                                     slack_signing_secret, slack_reviewer)
    print(f'Wiki UI: http://{host}:{server.server_port}')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
