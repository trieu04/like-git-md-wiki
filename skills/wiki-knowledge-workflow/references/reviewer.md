# Reviewer: worker, decisions and publication

## Use the worker

The reviewer works on contributions received as files/bundles. To ingest a bundle use `scan PATH --submitter AUTHOR` with the configured worker state/storage. For a `.contribution.md` file the UI provides **Tiếp nhận file** and a verified-author field. Its first tables show target and related-file versions. Import is an explicit pending-state operation, not a decision.

| Tool | Input | Output |
| --- | --- | --- |
| `GET /api/contribution` | none | Queue with IDs, authors and states |
| `GET /api/contribution/ID` | contribution ID | Base/body, reason, knowledge change, source snapshots/status, exact artifact, diff, bundle/artifact hashes, time, previous decision and `can_review` |
| `GET /api/wiki/versions?path=PATH` | URL-encoded Markdown path | Observed version references and tracked contributions with decisions, proposed diffs and publication receipts |
| `GET /api/wiki/version?path=PATH&version=VERSION` | Exact version from history | Immutable content, hash and capture time |
| `POST /api/contribution/import` | `file` (file text), `submitter` (verified author) | Imported ID, pending |
| `POST /api/contribution/ID/review` | `actor`, `reason`, boolean `approve`, original `bundle_hash`, `time`, `artifact` | approved/rejected |
| `POST /api/contribution/ID/publish` | `{}` | published/stale |

Read and artifact preview are one request; there is no separate preview endpoint. Approved/rejected/published contributions include their saved artifact for inspection. Only pending contributions may be reviewed; `can_review` also excludes the author from self-review. It does not assess source freshness or correctness.

## Approval rules

When assigned review, inspect pending contributions and assess source support, claim changes, scope, uncertainty and contradictions. Approve only when the exact artifact is supported by declared evidence, preserves valid existing knowledge, addresses the declared scope, and has no unresolved contradiction. Record the claims and sources checked and why the decision follows. The UI has fields for contribution ID, verified import author and decision reason. It shows the inputs and readable outputs, with no JSON runner.

If context is `stale`, inspect old snapshots and obtain current context using the CLI, then reject or request revision; do not approve. If it is `unversioned`, request versioned context when needed. If evidence is insufficient, leave pending and report what is missing, or explicitly reject with reasons. `current` alone does not justify approval.

Send the exact artifact/time/hash from the contribution response with your decision; do not recreate these fields. The configured reviewer identity may be an agent distinct from the author. An assigned publication step calls publish separately; the worker checks freshness again. Reading/importing a contribution never automatically approves it.

The API runs on localhost with caller-declared identities in a trusted environment; production authentication is not implemented.

## Merge files and resolve stale/conflict

Read [merge-conflicts.md](merge-conflicts.md) whenever the target or a source changed, two contributions touch the same file, or claims contradict each other. The worker publishes one complete approved artifact with a conditional write; it does not merge text or decide which claim wins. Scope rows describe impact and do not publish multiple files atomically.

## Use author metadata

`submitter` is the identity supplied by the trusted ingestion boundary. `author_metadata` is frozen, author-declared context: `name`, `role` (chức vụ), `expert` (the author's subject expertise), and `metadata_source`. Missing metadata means unknown; never infer expertise from a username. A metadata source is a provenance pointer, not proof of verification. Read it and declare/capture any document used as decision evidence.

Use expertise only for claims within that expertise. Use role to establish documented ownership or decision authority, not factual correctness. Prefer applicable authoritative evidence, effective dates and scope over seniority, submission order or confidence. If two experts disagree, compare their sources and assumptions; if evidence cannot settle it, leave pending with the disputed claims and needed domain-owner input, or reject with a revision request. Record which metadata was verified, how, and how it affected the decision. Never allow metadata to bypass distinct author/reviewer identities or freshness checks.
