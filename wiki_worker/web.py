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


class Application:
    def __init__(self, state, folder, fixture, reviewer, owner):
        self.state, self.folder, self.fixture = state, folder, fixture
        self.reviewer, self.owner = reviewer, owner
        self.index = files('wiki_worker').joinpath('static/index.html').read_bytes()

    def worker(self):
        storage = LocalFolderStorage(self.folder) if self.folder else FixtureRemote(self.fixture)
        return Worker(self.state, storage, self.reviewer, self.owner)

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
            self.json(HTTPStatus.NOT_FOUND, {'error': 'route not found'})
        except (Invalid, Conflict, UnicodeError) as exc:
            self.json(HTTPStatus.BAD_REQUEST, {'error': str(exc)})
        finally:
            if worker is not None:
                self.server.application.close(worker)

    def do_POST(self):
        worker = None
        try:
            route = urlsplit(self.path).path
            parts = route.strip('/').split('/')
            if route != '/api/contribution/import' and not (len(parts) == 4 and parts[:2] == ['api', 'contribution'] and parts[3] in ('review', 'publish')):
                return self.json(HTTPStatus.NOT_FOUND, {'error': 'route not found'})
            data = self.body()
            worker = self.server.application.worker()
            if route == '/api/contribution/import':
                if not isinstance(data.get('file'), str) or not isinstance(data.get('submitter'), str) or not data['submitter'].strip():
                    raise Invalid('contribution file and verified submitter required')
                ident = worker.import_contribution(data['file'].encode(), data['submitter'])
                return self.json(HTTPStatus.CREATED, {'id': ident})
            ident = unquote(parts[2])
            if parts[3] == 'review':
                keys = ('bundle_hash', 'time', 'artifact', 'actor', 'reason')
                if any(not isinstance(data.get(k), str) for k in keys) or not isinstance(data.get('approve'), bool):
                    raise Invalid('incomplete review decision')
                preview = dict(bundle_hash=data['bundle_hash'], time=data['time'], artifact=data['artifact'].encode())
                worker.review(ident, data['actor'], preview, data['approve'], data['reason'])
                return self.json(HTTPStatus.OK, {'state': 'approved' if data['approve'] else 'rejected'})
            return self.json(HTTPStatus.OK, {'state': worker.publish(ident)})
        except (Invalid, Conflict, UnicodeError) as exc:
            self.json(HTTPStatus.BAD_REQUEST, {'error': str(exc)})
        finally:
            if worker is not None:
                self.server.application.close(worker)

    def log_message(self, pattern, *args):
        print('%s - %s' % (self.address_string(), pattern % args))


def serve(host, port, state, folder, fixture, reviewer, owner):
    if host not in ('127.0.0.1', '::1', 'localhost'):
        raise Invalid('web UI currently binds to localhost only; authentication is not implemented')
    server = ThreadingHTTPServer((host, port), Handler)
    server.application = Application(state, folder, fixture, reviewer, owner)
    print(f'Wiki UI: http://{host}:{server.server_port}')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
