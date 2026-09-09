import datetime as dt
import hashlib
import json
import re

MARKER = '<!-- wiki-review:'
LIMIT = 1024 * 1024


class Invalid(ValueError):
    pass


class Conflict(Exception):
    """A conditional write definitively did not happen."""


def digest(data):
    return hashlib.sha256(data).hexdigest()


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise Invalid(f'duplicate JSON key: {key}')
        result[key] = value
    return result


def parse(data):
    try:
        return json.loads(data, object_pairs_hook=pairs)
    except (ValueError, UnicodeError) as exc:
        raise Invalid(f'invalid JSON: {exc}') from exc


def target_path(value):
    # Deliberately narrow portable subset; avoids URL, Windows and Unicode aliases.
    if not isinstance(value, str) or len(value) > 240:
        raise Invalid('invalid target path')
    parts = value.split('/')
    reserved = {'con', 'prn', 'aux', 'nul', *(f'com{i}' for i in range(1, 10)),
                *(f'lpt{i}' for i in range(1, 10))}
    if any(not re.fullmatch(r'[a-z0-9][a-z0-9_.-]*', p) or '..' in p
           or p.endswith('.') or p.split('.')[0] in reserved for p in parts):
        raise Invalid('target must be an unambiguous lowercase relative path')
    if not value.endswith('.md'):
        raise Invalid('target must be Markdown')
    return value


def read_file(path):
    if path.is_symlink() or not path.is_file():
        raise Invalid(f'expected regular file: {path.name}')
    with path.open('rb') as stream:
        data = stream.read(LIMIT + 1)
    if len(data) > LIMIT:
        raise Invalid('file exceeds 1 MiB limit')
    return data


