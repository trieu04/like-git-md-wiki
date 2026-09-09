"""SQLite test adapter; not the wiki storage format."""
import sqlite3
import uuid
from .common import Conflict, digest


class FixtureRemote:
    """Atomic local test transport. Identity here is NOT Microsoft authentication."""

    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS files(target TEXT PRIMARY KEY, item TEXT,
            version INTEGER, content BLOB);
          CREATE TABLE IF NOT EXISTS writes(receipt TEXT PRIMARY KEY, target TEXT,
            item TEXT, version INTEGER, hash TEXT);
        ''')

    def read(self, target):
        row = self.db.execute('SELECT * FROM files WHERE target=?', (target,)).fetchone()
        return dict(row) if row else None

    def write(self, target, content, expected):
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            old = self.read(target)
            actual = None if old is None else [old['item'], old['version']]
            if actual != expected:
                raise Conflict('remote version changed')
            item = old['item'] if old else str(uuid.uuid4())
            version = old['version'] + 1 if old else 1
            self.db.execute('INSERT OR REPLACE INTO files VALUES(?,?,?,?)',
                            (target, item, version, content))
            receipt = str(uuid.uuid4())
            self.db.execute('INSERT INTO writes VALUES(?,?,?,?,?)',
                            (receipt, target, item, version, digest(content)))
        return dict(receipt=receipt, target=target, item=item, version=version, hash=digest(content))

    def verify(self, result):
        row = self.db.execute('SELECT * FROM writes WHERE receipt=?', (result['receipt'],)).fetchone()
        return row is not None and dict(row) == result

    def receipt(self, receipt, prepared):
        row = self.db.execute('SELECT * FROM writes WHERE receipt=?', (receipt,)).fetchone()
        if row is None:
            return None
        result = dict(row)
        condition = prepared['condition']
        if (condition is None and result['version'] != 1) or (condition is not None and
                (result['item'] != condition[0] or result['version'] != condition[1] + 1)):
            return None
        return result

    def list_markdown(self):
        return [row[0] for row in self.db.execute('SELECT target FROM files ORDER BY target')]
