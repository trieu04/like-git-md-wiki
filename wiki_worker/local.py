"""Plain Markdown folder adapter for a trusted single-host wiki.

All writers MUST use this adapter's root-level lock. Filesystem rename does not
provide compare-and-swap against editors that bypass the lock. Keep published
wiki write permissions restricted to the worker; edit through proposals.
"""
import contextlib
import fcntl
import json
import os
import stat
import tempfile
import uuid
from pathlib import Path

from .common import Conflict, Invalid, LIMIT, digest, target_path


class LocalFolderStorage:
    def __init__(self, root):
        self.root = Path(root).absolute()
        self.root.mkdir(parents=True, exist_ok=True)
        if self.root.is_symlink():
            raise Invalid('wiki root cannot be a symlink')
        self.root = self.root.resolve()
        self.control = self.root / '.wiki-system'
        if self.control.is_symlink():
            raise Invalid('storage control directory cannot be a symlink')
        self.control.mkdir(mode=0o700, exist_ok=True)
        self.receipts = self.control / 'receipts'
        if self.receipts.is_symlink():
            raise Invalid('receipt directory cannot be a symlink')
        self.receipts.mkdir(mode=0o700, exist_ok=True)

    @contextlib.contextmanager
    def lock(self):
        fd = os.open(self.control / 'storage.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'a') as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            yield

    def path(self, target):
        target_path(target)
        path = self.root
        for component in target.split('/'):
            path = path / component
            if path.is_symlink():
                raise Invalid('symlinks are not allowed in wiki paths')
        return path

    @staticmethod
    def version(info):
        return [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns]

    def _read(self, target):
        path = self.path(target)
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        except FileNotFoundError:
            return None
        with os.fdopen(fd, 'rb') as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode):
                raise Invalid('wiki target must be a regular file')
            content = stream.read(LIMIT + 4097)
            after = os.fstat(stream.fileno())
        if len(content) > LIMIT + 4096:
            raise Invalid('wiki document exceeds read limit')
        if self.version(before) != self.version(after) or self.version(after) != self.version(path.stat()):
            raise Conflict('file changed during read')
        return dict(target=target, content=content, item=str(after.st_ino), version=self.version(after))

    def read(self, target):
        with self.lock():
            return self._read(target)

    def list_markdown(self):
        with self.lock():
            result = []
            for directory, dirs, files in os.walk(self.root, followlinks=False):
                # Contribution files are incoming workflow artifacts, not published wiki pages.
                # Keep them out of the document tree so an arbitrary contribution ID (for
                # example, uppercase XX123) cannot make /api/wiki fail path validation.
                dirs[:] = [d for d in dirs if d not in ('.wiki-system', 'contributions')
                           and not (Path(directory) / d).is_symlink()]
                for name in files:
                    if name.endswith('.md'):
                        relative = (Path(directory) / name).relative_to(self.root).as_posix()
                        self.path(relative)
                        result.append(relative)
            return sorted(result)

    @staticmethod
    def sync_directory(path):
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def write(self, target, content, expected):
        with self.lock():
            old = self._read(target)
            actual = None if old is None else [old['item'], old['version']]
            if actual != expected:
                raise Conflict('local wiki version changed')
            path = self.path(target)
            # Persist each new directory entry before acknowledging a write.
            parent = self.root
            for part in target.split('/')[:-1]:
                child = parent / part
                if not child.exists():
                    child.mkdir()
                    self.sync_directory(parent)
                parent = child
            fd, temporary = tempfile.mkstemp(prefix='.wiki-write-', dir=path.parent)
            try:
                with os.fdopen(fd, 'wb') as stream:
                    stream.write(content)
                    stream.flush()
                    os.fsync(stream.fileno())
                if expected is None:
                    try:
                        os.link(temporary, path)
                    except FileExistsError as exc:
                        raise Conflict('local target already exists') from exc
                else:
                    os.replace(temporary, path)
                self.sync_directory(path.parent)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
            current = self._read(target)
            if current is None or current['content'] != content:
                raise Invalid('local write verification failed')
            result = dict(receipt=str(uuid.uuid4()), target=target, item=current['item'],
                          version=current['version'], hash=digest(content))
            record = dict(result=result, condition=expected)
            # Crash between file rename and this receipt remains uncertain.
            with (self.receipts / (result['receipt'] + '.json')).open('x') as stream:
                json.dump(record, stream)
                stream.flush()
                os.fsync(stream.fileno())
            self.sync_directory(self.receipts)
            return result

    def _receipt(self, receipt):
        try:
            if str(uuid.UUID(receipt)) != receipt:
                return None
        except (ValueError, TypeError, AttributeError):
            return None
        path = self.receipts / (receipt + '.json')
        try:
            with path.open() as stream:
                return json.load(stream)
        except (FileNotFoundError, ValueError):
            return None

    def verify(self, result):
        record = self._receipt(result['receipt'])
        return record is not None and record['result'] == result

    def receipt(self, receipt, prepared):
        record = self._receipt(receipt)
        if record is None or record['condition'] != prepared['condition']:
            return None
        return record['result']
