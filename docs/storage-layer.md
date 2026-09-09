# Processing layer for a Markdown wiki

The wiki is a tree of Markdown files with relative links. A local folder or
SharePoint stores that tree. The worker's SQLite database stores processing
state, frozen bundles, and history; it does not replace the wiki format.

```text
Local folder ─── adapter ───┐
                           ├── WikiStorage ── Worker: submit → review → publish
SharePoint ──── adapter ────┘                         │
                                            SQLite state/history
```

## Working components

- `LocalFolderStorage`: reads an existing wiki and publishes `.md` files directly,
  preserving relative paths. `.wiki-system/` holds the adapter lock and receipts.
- `FixtureRemote`: a SQLite adapter for tests, separate from the workflow.
- `WikiStorage`: a shared interface for list/read/conditional write/verify/receipt.
  Versions are opaque tokens: the workflow does not assume increasing version
  numbers or access the adapter's database.
- `Worker.submit(manifest, base, proposed, submitter)`: accepts downloaded bytes
  from any source; proposals do not have to reside in a local folder.
- `Worker.propose(...)`: captures the base from the configured storage and creates
  a proposal. This changes worker state only; the wiki changes after approval
  and publication.

Run from the repository, replacing the example paths with your own:

```sh
python -m wiki_worker.cli --folder /path/to/wiki --state /path/to/worker-state --reviewer reviewer list
python -m wiki_worker.cli --folder /path/to/wiki --state /path/to/worker-state --reviewer reviewer show index.md
python -m wiki_worker.cli --folder /path/to/wiki --state /path/to/worker-state --reviewer reviewer context index.md --source source.md
# Agent creates the bundle using the skill before scan:
python -m wiki_worker.cli --folder /path/to/wiki --state /path/to/worker-state --reviewer reviewer scan /path/to/contribution-bundle --submitter author
python -m wiki_worker.cli --folder /path/to/wiki --state /path/to/worker-state --reviewer reviewer review change-1 --actor reviewer --reason 'Checked the sources'
python -m wiki_worker.cli --folder /path/to/wiki --state /path/to/worker-state --reviewer reviewer publish change-1
```

## Web UI

Start the local UI with the same storage/state/reviewer configuration:

```sh
python -m wiki_worker.cli --folder /path/to/wiki --state /path/to/worker-state --reviewer reviewer web --port 8080
```

Open `http://127.0.0.1:8080`. The UI uses HTML, Pico CSS, and AlpineJS;
Pico/Alpine load from CDNs, so the browser needs network access for styling and
interaction. The HTTP backend uses the Python standard library and the same
`Worker` as the CLI. The UI can generate contribution files from saved context,
ingest them for review, display contributions with diffs/artifacts, record
decisions, and publish. Agents discover documents through the filesystem.

The web server only binds to localhost because login, sessions, and CSRF
protection are not implemented. Reviewer and submitter identities still come
from the trusted pilot environment. Do not reverse-proxy or expose this port to
the network. A future SharePoint adapter must supply authenticated Microsoft
identities to the API instead of accepting identities from a form.

Use one fixed state directory per wiki. Do not change storage for a state that
already contains proposals. `--actor`/`--submitter` are identities supplied by the
trusted CLI environment, not Microsoft logins. Restrict execution under the
worker account.

The local adapter uses a shared lock per wiki root, temporary files, fsync, and
atomic rename. Creation uses an operation that cannot replace an existing file.
All writers must honor the adapter lock; wiki write access should belong only
to the worker. Editors or sync programs that ignore the lock may write between
the check and rename, so a SharePoint-synced local folder is not equivalent to a
SharePoint adapter with ETags. External changes before publication are detected
through base hashes/versions, but there is no compare-and-swap guarantee with
uncooperative writers.

## SharePoint integration boundary

This release has no SharePoint HTTP adapter. Such an adapter implements
`WikiStorage` and is passed to `Worker(root, storage, reviewer)`, without changing
review/publication rules:

1. `list_markdown`: list logical paths within the configured wiki root.
2. `read`: return `content` (bytes), `item`, and `version` (ETag) from the same
   version; return `None` only for confirmed absence.
3. `write`: accept an `[item, version]` condition or `None` for creation. Raise
   `Conflict` only when the write definitively did not happen; timeouts must
   enter the uncertain-outcome workflow.
4. `verify` and `receipt`: verify evidence for a specific operation, including
   target, artifact hash, and original write condition, not just current content
   hashes.
5. Proposal ingestion: download manifest/base/proposed, bind authenticated
   identity to the downloaded manifest version, and call `Worker.submit`. The
   layer validates schema/hashes and freezes bytes just as for local folders.

HTTP/authentication and tenant verification of conditional writes/ETags are
required before using live SharePoint. Do not infer these guarantees from the
fixture or a synced folder. See the verification cases in [runtime](runtime.md).
