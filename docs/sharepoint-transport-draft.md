# SharePoint transport — initial draft

This document preserves an earlier file-transport and publication proposal, not the current specification. The [README](../README.md) and [Phase 1 design](design.md) take precedence. Merging files does not accept claims; the current Phase 1 uses document revisions, not a wiki-wide HEAD or the blanket PR staleness rule below.

Phase 1 proposal: a Markdown wiki on Microsoft 365 SharePoint, with every employee able to contribute through an agent; each contribution is a PR tied to an immutable snapshot. This is a discussion design, not an implemented system or SharePoint API behavior verified on a real tenant.

## Design perspective

File-based PRs and hash/tree versions are suitable ideas. However, suffixes should only identify files; PR identity, status, and base version belong in a schema-defined manifest. A PR may change multiple documents and therefore needs its own directory/bundle, not just one suffixed file.

Distinguish three concepts:

- SharePoint stores and shares documents, authenticates users, and retains individual file version history.
- System snapshots pin the entire document tree and content read by an agent. Individual SharePoint file histories do not replace a whole-wiki snapshot.
- A PR describes proposed changes against a specific snapshot. The worker validates, a reviewer approves, and one publisher updates the official wiki version.

Phase 1 does not resolve knowledge merge conflicts. It must still detect base changes to prevent overwrites: old PRs become `stale` and need a revision against the new HEAD. No automatic merge, even when two PRs change different files; this could be relaxed later.

## Proposed layout

```text
SharePoint document library/
  wiki/                         # Reader-facing Markdown with relative links
  contributions/
    <pr-id>/
      revisions/
        <revision-id>/
          payload/docs/topic.md # Complete replacement; preserves logical path
          pr.ready.json         # Uploaded last; immutable after submission
  .wiki-system/
    objects/sha256/<hash>        # Immutable blobs retaining original bytes
    trees/<tree-hash>.json       # Path -> blob hash
    commits/<commit-hash>.json   # Tree, parent, publication metadata
    refs/main.json              # HEAD; conditionally updated
    pr-status/<pr-id>.json       # Worker-managed state
    publish-journal/<job-id>.json
```

This is a logical layout; a leading dot does not automatically protect `.wiki-system` in SharePoint. Apply separate system-area permissions and check tenant filename/path limits. If object counts grow large, evaluate a separate object store in a later phase; Phase 1 prioritizes keeping all shared data within Microsoft 365.

Suffixes should be minimal and precise: `.ready.json` signals submission. Contribution types (`add`, `modify`, `delete`, `rename`) belong in the manifest. Do not encode the entire PR lifecycle by renaming files: renames create extra sync events and are not reliable state transactions.

## PR manifest

Abbreviated example; hash values are placeholders:

```json
{
  "schema_version": 1,
  "pr_id": "pr-<uuid>",
  "revision_id": "rev-<uuid>",
  "title": "Expand onboarding guidance",
  "base_commit": "sha256:<commit-hash>",
  "context": {
    "tree": "sha256:<tree-hash>",
    "read_paths": ["docs/onboarding.md", "docs/security.md"]
  },
  "changes": [
    {
      "op": "modify",
      "path": "docs/onboarding.md",
      "expected_blob": "sha256:<old-blob-hash>",
      "payload": "payload/docs/onboarding.md",
      "new_blob": "sha256:<new-blob-hash>"
    }
  ]
}
```

`add` requires an absent path; `modify`/`delete` require a matching old hash; `rename` declares source path, destination path, and source hash. Phase 1 uses full replacements instead of patches to simplify application and verification. Renaming does not repair backlinks automatically: the agent must include related link changes in the same PR.

Do not trust self-declared JSON author fields. Use authenticated Microsoft 365 identity at submission or trusted platform metadata. If all uploads share a service principal, a separate authenticated submission channel is needed to preserve employee attribution.

## Snapshots and agent context

1. Blob hash = SHA-256 of original bytes, without silent normalization before hashing.
2. A tree is a deterministically sorted list of logical paths and blob hashes. Specify UTF-8, `/` separators, Unicode NFC, no root escapes, and no duplicate names after normalization/case-folding under repository policy.
3. Hash trees/commits from canonical JSON with a fixed schema version; document the canonicalization algorithm when implementing it. Commits contain tree hash, parent commit, and publication metadata; tree hashes depend only on the content tree.
4. Persist immutable blobs/trees/commits before allowing references to point to them. Hashes without retained content cannot reproduce context.
5. Agents receive `base_commit` and read through that snapshot, without mixing in live `wiki/` reads. `read_paths` supports auditing; external sources require separate snapshots/provenance for complete context reproduction.

Hashes provide identity and integrity checks; they do not replace permissions, signatures, or actor audit logs.

## PR and publication workflow

```text
draft -> submitted -> validating -> ready -> approved -> publishing -> merged
                         |           |         |
                         v           v         v
                       invalid    rejected    stale
```

- Agents upload payloads first and the `.ready.json` manifest last. A suffix alone does not establish upload completion: the worker downloads all files and verifies hashes. Retry incomplete synchronization before declaring a PR invalid.
- Cron scans the inbox at a configurable interval. Ingestion is idempotent on `(pr_id, revision_id, manifest_hash)`; identical IDs with different content are rejected. Submitted revisions are immutable.
- The worker validates schema, paths, permissions, payload hashes, base commit, per-file preconditions, and internal links. Resolve links against the projected result tree; external links need not be crawled. Explicitly configure whether broken links warn or block.
- Reviewers approve the exact revision and manifest hash. Payload or base changes invalidate the old approval. Agents cannot grant themselves approval by editing status files.
- One publisher with a durable lease publishes. Recheck `base_commit == HEAD` first; otherwise mark `stale` and do not apply the PR.
- The publisher creates all new objects/trees/commits, then updates `refs/main.json` through compare-and-swap using an API-supported ETag/write condition. If HEAD changes and the update fails, the PR is not merged.
- Advancing HEAD is the logical commit point. Then materialize the new tree into `wiki/`; report `merged` only after the projection is complete. Journal progress so work can resume after a crash, including immediately after advancing HEAD.

SharePoint does not provide a default atomic transaction for replacing many Markdown files. Direct `wiki/` readers may see intermediate states during multi-file publication. Agents always read snapshots through HEAD. If human readers also require an atomic version, provide a reader that resolves content by commit or use immutable release folders; this product choice must be settled before implementation.

## Synchronization and permissions

- Cron is the background recovery mechanism; Graph delta/webhooks may reduce latency. Do not assume notifications arrive once or in order.
- Bound work per run, retry with backoff and API throttling guidance, and retain durable cursors/checkpoints. Recheck incomplete PRs after restart.
- Store worker state, leases, and journals durably. A single-process MVP can use SQLite on a separate volume; never put an open SQLite database in a SharePoint sync folder.
- Employees read the wiki and create contributions; the worker owns snapshot/ref/status areas and publication rights. Restrict official wiki writes so changes go through PRs.
- If direct `wiki/` edits must be supported, import them as separate commits and detect drift before publication. This is outside the MVP; never silently overwrite manual edits.
- Contribution permissions must prevent others from changing submitted proposals. The worker freezes revisions in the object store at ingestion; approval always binds to frozen hashes.

## Proposed MVP

1. Agent tools/API: `get_head`, `read_snapshot`, `submit_pr`, `get_pr_status`.
2. Snapshot store and a command to import the existing wiki as an initial commit. Build the initial snapshot during a no-edit window or recheck metadata/versions to discard inconsistent reads.
3. PR manifests, validator, cron worker, and durable state.
4. Authenticated CLI or HTTP review/approve/reject; one publisher, conditional HEAD updates, and crash recovery.
5. Markdown link checks and change reports; no automatic resolution of knowledge disagreements.

Outside scope: Git protocol, arbitrary branches, three-way merging, knowledge conflict resolution, a rich review UI, semantic search, automatic LLM approval, and old-object garbage collection. Retain all snapshots in the MVP so old PRs remain reproducible.

## Validation criteria

- Rereading an old commit returns the exact content after HEAD changes.
- For two PRs with the same base, the second becomes stale after the first publishes.
- Repeated worker runs or duplicate events do not publish twice.
- Crashes before/after HEAD updates and during materialization recover correctly from the journal.
- Missing payloads, post-submission changes, path traversal, and approval of the wrong revision are blocked.
- Multi-file PR link checks cover the entire result tree; renames preserve links within the checker's supported scope.
- Out-of-workflow edits are detected and stop publication instead of being overwritten.

## Decisions needed at implementation start

- Is the wiki read through SharePoint, synced files, or a Markdown viewer? Rendering and link resolution differ across channels.
- Can official wiki write access be restricted and all changes required to go through agents/PRs?
- Where will the worker run, will it use application identity or delegated access, who may review, and which sites/libraries are authorized?
- What are the wiki size, attachment types, and tolerance for intermediate states in `wiki/`?

Specific Microsoft Graph behavior for conditional writes, uploads, identity metadata, delta, and site/library permissions must be verified against official API documentation and the target tenant before choosing endpoints/SDKs. This design does not assert that any endpoint already provides all these properties.
