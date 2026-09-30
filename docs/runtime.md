# Markdown workflow runtime

Python 3.11+, Linux, standard library only. Run from the repository with
`python -m wiki_worker.cli`, or install with `python -m pip install -e .`.

This release includes a plain Markdown local-folder adapter and the fixture fallback in implementation steps 1–3. See [storage layer](storage-layer.md) for `--folder`, list/show/propose commands and the SharePoint adapter contract. The examples below use the test fixture.
It does **not** connect to SharePoint or authenticate Microsoft identities.
`--submitter`, `--actor`, and `--reviewer` are simulated IDs in a trusted local
experiment. Do not use this CLI as a production authorization boundary.
No tenant credentials or verified transport were available during implementation.

## Try the complete flow

Create a proposal directory with `proposed.md` and `proposal.ready.json`:

```sh
mkdir -p /tmp/wiki-demo/proposals/demo
printf 'Hello wiki\n' > /tmp/wiki-demo/proposals/demo/proposed.md
python - <<'PY'
import hashlib, json
from pathlib import Path
p = Path('/tmp/wiki-demo/proposals/demo')
(p / 'proposal.ready.json').write_text(json.dumps({
    'schema_version': 1, 'id': 'demo', 'target': 'hello.md',
    'base_hash': None,
    'proposed_hash': hashlib.sha256((p / 'proposed.md').read_bytes()).hexdigest(),
    'reason': 'Introduce the pilot', 'sources': []
}))
PY
```

Use the same state directory, remote and reviewer configuration for every command:

```sh
python -m wiki_worker.cli --state /tmp/wiki-demo/state --fixture /tmp/wiki-demo/remote.sqlite --reviewer reviewer scan /tmp/wiki-demo/proposals/demo --submitter contributor
python -m wiki_worker.cli --state /tmp/wiki-demo/state --fixture /tmp/wiki-demo/remote.sqlite --reviewer reviewer review demo --actor reviewer --reason 'Checked the text'
# Read the preview, then type approve.
python -m wiki_worker.cli --state /tmp/wiki-demo/state --fixture /tmp/wiki-demo/remote.sqlite --reviewer reviewer publish demo
python -m wiki_worker.cli --state /tmp/wiki-demo/state --fixture /tmp/wiki-demo/remote.sqlite --reviewer reviewer status
```

For updates, save the **entire** current remote file in `base.md`, including its
status block, and put its SHA-256 in `base_hash`. Put only the desired document
body in `proposed.md`. Send the manifest last. Each file is limited to 1 MiB;
Markdown must be UTF-8. Paths are relative to the wiki root and deliberately
restricted to lowercase ASCII portable names ending in `.md`. IDs are immutable;
change the ID when revising a proposal. A repeated scan validates the incoming
payload again; later review and publish use the frozen bytes, never inbox files.
Use `review --reject` to reject. Neither rejected nor stale proposals can publish.

For a semantic/content disagreement, use `discuss ID --action open` to place an approval hold, `comment` to append evidence or record no consensus, and `resolve --resolution-kind ...` only when the exact frozen proposal is supported. `reopen` restores a resolved hold after new objections. A review is bound to the discussion version it displayed; an intervening entry requires rereading. Open disputes can be rejected to request revision but cannot be approved.

The CLI displays reason, sources, diff and complete final artifact before asking
for confirmation. It releases the lock while waiting and rechecks state when
saving the decision. Worker state belongs to a trusted OS account. Contributors
must not have write access to its files or execution access as that account.

## Storage and recovery

`state.sqlite` stores original manifest bytes, base, proposed content, artifact,
decision, publish intent, receipt, resolution evidence and history. Frozen content
is stored as SQLite BLOBs instead of a separate filesystem bundle directory;
this makes content and its state references durable in the same transaction.
The `history` table is finalized before `published` is reported. Publication now
registers the exact verified artifact in `document_versions` immediately and
records its reference as `published_version` in history. The previous content is
also recorded before a write. Retrying a completed publication adds no version.
Older publication records are retained as-is; their artifacts remain available
through contribution inspection, but missing historical version labels are not
invented or backfilled.

Agents can read `GET /api/wiki/versions?path=PATH` for ordered observed versions
and contribution changes (author identity/declared metadata, base/proposed hashes,
proposed diff, decision, resolution evidence and publication receipt).
`GET /api/wiki/version?path=PATH&version=VERSION` returns exact snapshot content,
hash and capture time. URL-encode paths and versions. These historical reads do
not observe remote storage; use the context CLI or `/api/wiki/document` for a
current observation. Unknown versions and invalid paths return HTTP 400; a path
with no tracked history returns empty lists. External edits between observations
are not tracked. History is currently returned without pagination.

Keep the state
on a durable local filesystem supporting SQLite locking and `flock`; do not put
it in a SharePoint sync folder. All worker mutations share `worker.lock`.

A publish moves through durable `writing`, `written`, and `done` phases. Any
restart with `writing` blocks **all** proposals to that target; other targets
remain usable. A failure while completing history leaves `written`; rerun publish
to finish without another remote upload. A definitive conditional conflict or
base mismatch produces `stale`, requiring a new proposal and review.

For an unknown outcome, stop and inspect independent remote operation evidence.
`fixture-receipts` displays the fixture's atomic write ledger. Then use:

```text
resolve ID --actor reviewer --outcome written --evidence 'Investigation and receipt details' --receipt RECEIPT
resolve ID --actor reviewer --outcome not-written --evidence 'Independent evidence that no write committed'
```

These are subcommands with the same global options as above. Matching content
alone is insufficient for a `written` resolution. A receipt must match the target,
artifact and expected successor version. `not-written` is a trusted operator
assertion, audited with identity/time/evidence; do not use it to retry an outcome
that is still unknown. The next publish checks the base again.

`fixture-put TARGET FILE` simulates an external writer for experiments; it is not
a wiki administration or rollback command. Restore by copying the body of an old
version into a **new** proposal against the current base. Reserved status markers
are rejected in proposed content so the new review creates one fresh status block.

## Scheduling and backup

For a local-folder or fixture experiment, a cron wrapper can scan known proposal folders and
publish known approved IDs using the CLI above. Use absolute interpreter, repo,
state and fixture paths, pin the reviewer configuration, and keep stderr visible
to the operator. Do not schedule review or automatic uncertainty resolution.
Publish retries are safe; non-approved or blocked proposals exit nonzero. There
is no production SharePoint cron deployment yet.

`backup /absolute/path/new-backup.sqlite` holds the worker lock and uses SQLite's
backup API, including all frozen bytes and history. Back up the separate fixture
remote only while all fixture writers are stopped. To restore, stop cron and all
workers, preserve the current state, and copy the backup to `state.sqlite` in a
fresh private state directory. Inspect all `writing`/`written` records and remote
receipts before restarting. A stale backup can predate a committed remote write;
do not infer that an approved record means no write happened. Reconcile that
history manually first. Never restore the remote over newer content.

## Verification and live integration gate

Run `python -m unittest discover -s tests -v`. Tests use real SQLite and an atomic
fixture transport, inject version races and failures, and cover byte identity,
review restrictions, input validation, repeat scans/publishes, backup and manual
resolution across restart. Fixture content/item/version are read from a single
row; conditional writes and operation receipts commit in one transaction.

This proves the local workflow, **not SharePoint behavior**. Before adding a live
transport and starting the pilot, record evidence from an isolated tenant folder:

- Read/upload and conditional create/update: bytes, item identity and ETag must
  belong to the same version even during a concurrent edit. Verify create cannot
  replace an existing item and failed conditions cannot write.
- Bind the inbox manifest version to an authenticated submitter and prevent
  another contributor changing it under that identity. Authenticate the reviewer
  through Microsoft 365 and compare immutable account IDs.
- Verify only the worker writes wiki/history, and check actual Markdown rendering
  of reviewed/unreviewed labels. Implement controlled import preserving originals
  and using verified conditional writes before labeling existing documents.
- Exercise expired tokens, 429/backoff, denied access and timeouts; absence must
  be distinguishable from failed reads. Demonstrate remote receipt/version
  evidence for manual investigations.
- Drill backup/restore and collect queue age, correction time and sample errors.

No live API guarantees, permissions, rendering, import, or pilot measurements
have been claimed or verified by this implementation.

## Agent context and review tools

See [agent workflow](agent-workflow.md) for the contributor and reviewer skills. Contributors discover files directly, run `context TARGET --source SOURCE`, then create a `.contribution.md` file whose scope table lists the primary file first and all related or impacted files with versions. `scan PATH --submitter AUTHOR` ingests that file or a compatible directory bundle; the reviewer UI can import the Markdown file too. No author HTTP submission endpoint is provided. Reviewer reads use `/api/contribution/ID`, which includes the exact artifact; decisions and publication use `/review` and `/publish` under that path. Outdated context is rejected rather than silently rebased. The configured reviewer must be distinct from the contributor. The worker does not run a model, schedule reviews or decide approval itself.

The SQLite backup now also includes `document_versions`, the immutable observed source snapshots, and the append-only semantic discussion log. Version labels use UTC observation dates and per-document daily sequences, not publication or effective dates. Legacy proposals without context are reported as unversioned.

## Reviewer workflow playground

Run `make playground` and open the printed localhost URL. The disposable demo contains an A/B/C concurrent-contribution case and an explicit semantic contradiction (`X is blue` versus `X is red`). Use [the reviewer demo runbook](reviewer-demo-runbook.md) to inspect evidence, classify conflicts, record discussion decisions, and keep merge authoring, approval and publication separate. The temporary wiki and SQLite state are removed when the server exits; this command never writes `wiki-en`.
