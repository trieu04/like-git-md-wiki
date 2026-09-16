# MVP design

## Scope

Prove one workflow: **submit a change → designated reviewer reviews it → publish exactly what was approved → trace and correct mistakes**. A fixture runtime is available; see the [guide](runtime.md). Live SharePoint integration remains unverified.

Use one Markdown folder on SharePoint, one configured reviewer (human or agent), and one worker on one host. Each proposal changes or adds one file. Renames, deletions, attachments, multiple-file changes, and permissions across multiple domains are outside scope. Employees and agents submit proposals; only the worker writes the official wiki. Verify write permissions and authentication before the pilot.

Prioritize a small working flow. Rare cases or uncertain outcomes may stop for operator intervention; a general automatic recovery system is not required yet.

## Data

```text
wiki/                       Shared documents
proposals/<id>/
  base.md                   Complete base; omitted for new files
  proposed.md               New content without the system status block
  proposal.ready.json       Manifest submitted last
history/<id>/               Frozen bundle, decision, and publication result
```

The manifest contains a schema version, proposal ID, target path, base hash (null for creation), proposed hash, reason, and sources/context when available. SHA-256 is calculated over original bytes; retain the base to reconstruct the content. The bundle hash is the hash of the exact manifest bytes containing the file hashes. Preserve the manifest rather than serializing it again during verification. Paths must remain inside the wiki; reject root escapes, ambiguous names, and duplicate JSON keys.

The worker obtains the submitter from authenticated SharePoint metadata bound to the ingested manifest version, not a self-declared author field. Inbox permissions must prevent someone from editing a proposal under an earlier submitter's identity. If agents share an application identity that cannot identify the submitter, restrict use to internal experiments until an appropriate authenticated submission mechanism exists.

Proposals are immutable after ingestion; revisions need a new ID. The same ID and bundle is a retry; a different bundle is an error. A suffix is only a signal: the worker must download everything, verify hashes, and durably freeze the bundle before review.

## Runtime

A Python program provides `scan`, `review`, `publish`, and `status`; cron periodically runs scan/publish. SQLite and frozen bundles live on a separate durable volume, outside SharePoint sync. SQLite tracks state/progress; history retains the audit record. Persist content before allowing database references to it.

State-changing commands share a process lock. Do not hold it while waiting for review; recheck state when confirming a decision. CLI review runs in a trusted environment. Contributors must not modify the database/bundles or execute arbitrary commands as the worker.

The localhost web UI/API supports file ingestion, reading contributions with artifacts, review, and publication. Network access authentication is not implemented. Agents contribute files or bundles. No queue service or workflow framework is required.

## Review and publication

1. Scan validates payloads, paths, and hashes, identifies the submitter, and freezes the bundle.
2. The designated reviewer inspects the diff, reason, and sources through the CLI. Authenticate through Microsoft 365 and check the reviewer against the pilot configuration using account IDs, not self-declared names. Authors cannot approve their own work. If the only reviewer is also the author, leave the proposal pending.
3. The worker builds the final file, including its status block, and shows it before confirmation. Retain this file with the bundle hash, artifact hash, reviewer, timestamp, and reason. Publish the exact approved bytes; do not regenerate metadata using a later time or configuration.
4. Before publication, check the entire remote file against the base hash. Content bytes, item ID, and version/ETag must belong to the same verified version. Do not pair old content with a new ETag from a separate metadata read. Write conditionally against that item/ETag; creation must fail if the path already exists. Use only operations proven by the spike to meet these conditions. Permission and network errors must not be treated as absence.
5. Durably store the bundle, decision, and prepared publication before writing remotely, including target, artifact hash, and write condition (item/ETag or create-only). After writing, retain the remote result, verify the artifact, and finish history before reporting `published`. If only history is incomplete, finish recording it without uploading the wiki again.

When a timeout or crash leaves the write outcome unknown, block all publication to that target while investigating remote storage/history; other files may proceed. After restart, resolve incomplete writes before accepting new publications to that target. Matching hashes prove content equality, not that a particular operation committed. The operator records evidence and a written/not-written conclusion before unblocking; unresolved cases remain blocked. Automatic reconciliation of every case is unnecessary for now. Do not blindly retry writes, obtain a new ETag to bypass the original condition, or roll back blindly.

Minimum states: `pending`, `approved`, `published`, `rejected`, and `stale`. Store publication phases, transient errors, investigation flags and the semantic dispute hold separately. Investigation blocks publication until a conclusion is recorded. An open semantic dispute blocks approval but still permits rejection with a revision request. If the base changes before writing, mark `stale` and require a new proposal. An unknown write outcome is neither stale nor published. `published` records a historical publication; it does not mean the remote file remains at that version forever.

## Semantic content disputes

The MVP records a reviewer-mediated discussion against one immutable contribution. Each event stores an ordered sequence, configured reviewer, server time, action, rationale, optional resolution kind and related contribution IDs, bound to the proposal's bundle hash. `open` and `reopen` establish an approval hold; `comment` preserves it; `resolve` removes it from the unchanged proposal without editing or approving anything.

Contribution reads return the complete discussion, its version and the derived hold. Review decisions must include the version displayed to the reviewer, so a concurrent objection invalidates an older decision attempt. No consensus remains an open hold. Changed wording or new evidence requires a new contribution and fresh review.

The worker does not detect contradictions, evaluate evidence, contact domain experts, count votes, or propagate a hold across proposals. The current localhost trust boundary permits only the configured reviewer to record discussion events. See [semantic conflict research and design](semantic-conflicts.md) for rationale and limits.

## Reader status and corrections

The worker adds a Markdown status block at the beginning of the file with owner, proposal ID, and reviewer/date. Reserved markers separate it from the content. Reject these markers in `proposed.md` to prevent duplicate blocks or old approval labels in new content. The base hash still covers the entire remote file. A “reviewed version” label does not guarantee absolute correctness.

Import happens during controlled setup: retain originals, add `unreviewed` labels with version checks, and track processed files so retries do not stack labels. The pilot must check actual reading channels; synced/offline folders may show older versions.

When an error is found, submit a correction or a temporary withdrawal notice; the owner prioritizes its review. Restoration uses the body of an older version as a new proposal against the current base, with a new approval and status block. Never overwrite directly.

The MVP does not automatically track source changes, overdue reviews, or issues. The operator uses existing tools.

## Minimum operations

- Only the worker writes wiki/history; folder names do not establish permissions. Use documents with the same access scope during the pilot, and do not copy restricted sources into a more widely accessible wiki.
- Create a consistent SQLite backup through its backup API, including referenced bundles/artifacts; pause writes while taking the backup set. Rehearse restoration before the pilot. Check remote state and incomplete publications before restarting cron; never overwrite newer remote content with old backup state.
- Limit proposal sizes, retry transient failures with backoff, and keep tokens out of logs. Proposal content is data and must not execute.
- Hashes prevent version mix-ups; they do not replace authentication or write permissions.

Atomic multi-file updates, graph snapshots, and temporal queries are not included. Context beyond recorded bases/sources is not guaranteed to be reproducible. Expand only when the pilot reveals a concrete problem.

## Content contributions

Agents discover and read files directly, obtain versions through the CLI, and prepare bundles. The UI creates `wiki-contribution-v3` files for reviewer ingestion: scope/impact uses `file | version | impact`, and sources use `file | version`. Proposed content appears before Base content, both as plain Markdown. Separators use a dedicated Boundary absent from the content so ordinary separators remain unambiguous. The Markdown parser accepts only v3. The worker resolves hashes from registered file/version snapshots and pins internal context; payload hashes are still checked in metadata. The UI can construct final content with a unique replacement or an append. Manifests may include `knowledge_change` with `before`, `after`, and `scope`; validation checks that a unique replacement reproduces the complete proposed content after stripping the old review block. This metadata belongs to the bundle hash and remains intact through review and history.

This knowledge diff is author-declared, not an automatic semantic inference. There is no AI model, contradiction detection, source verification, or automatic editing of related files. The text diff and complete artifact remain necessary to inspect exactly what will be published.

## Agent tools and immutable context

See the [two-role skill workflow](agent-workflow.md). The worker provides versions through the context CLI and ingests files/bundles through scan or the reviewer form. `/api/contribution/ID` combines inspection and the artifact. A reviewer agent may use review tools when assigned pending work; the worker enforces valid decisions without reasoning or approving on the agent's behalf.

A manifest may contain `context` referencing the target and source versions. SQLite stores snapshots with paths, `YYYYMMDD-N` labels (UTC observation date and per-document sequence within that day), SHA-256, content, and timestamps. Agent workflows require context; legacy workflows remain compatible without it. Source changes block new proposals and approval; changes after approval make publication stale. Reviewers may still reject proposals with stale sources. Snapshots are never overwritten; history and backups preserve references/context.

Freshness checks do not judge knowledge correctness, detect missing sources, or guarantee an atomic transaction across multiple sources with external writers. The worker has no automatic scheduler or model.
