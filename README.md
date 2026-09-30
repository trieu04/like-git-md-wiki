# Like Git SharePoint Wiki

Goal: keep the wiki trustworthy as its knowledge and number of human and AI contributors grow.

The MVP needs to prove one workflow: **submit a change → designated reviewer reviews it → publish exactly what was approved → trace and correct mistakes**. The repository includes a Python/SQLite layer with a local Markdown folder adapter and test fixtures. SharePoint integration and Microsoft 365 authentication have not been verified.

## Initial scope

- Preserve the existing Markdown wiki and links on SharePoint.
- Each proposal changes one file and includes the base content, hashes, new content, reason, and sources when available.
- A configured reviewer (human or agent) decides through the review tools. Authors cannot approve their own work, and the system never decides approval itself.
- Before publication, verify that the current file still matches the base and the payload still matches the approval. Otherwise require resubmission and review; do not merge automatically.
- Publish the exact approved final file, including its status block. If a write outcome is unknown, block publication to that target pending investigation. The MVP does not automatically recover every case.
- Retain earlier content, submitter, reviewer, and timestamps for auditing. Corrections require new proposals; restoration also goes through version checks.
- Clearly show whether a document is unreviewed or a particular version has been reviewed, and identify the responsible person. A review label does not guarantee absolute correctness.

Conflicts are handled against the frozen three-way base: if B was authored from v1 after A published v2, the wiki is never destructively rolled back. The reviewer sees v1, v2 and B, then keeps v2, accepts B as a fresh v2-based proposal, or supplies a merged proposal. The old contribution is closed and any replacement receives a fresh review. Discussions are separate file/section-anchored records; they are not embedded in a contribution.

## Validation

Try a small document set with one designated reviewer. Check that readers recognize review status, two agents editing the same file cannot overwrite each other, restarting the worker does not publish twice, and incorrect content can be traced to its sources and corrected. Manually track pending proposal age, correction time, and errors found in sample checks.

## Implementation documents

- [MVP design](docs/design.md)
- [Plan](docs/plan.md)
- [Implementation plan](docs/implementation-plan.md)
- [Semantic conflict research and MVP design](docs/semantic-conflicts.md)

`knowledge-model-horizon.md` and `sharepoint-transport-draft.md` are historical references, not a backlog or implementation requirements.

## Runtime

See the [runtime and recovery guide](docs/runtime.md). Run all checks with `make test`. Use `--folder` for a real Markdown wiki and `--fixture` for tests; there is no SharePoint HTTP connection yet.

The wiki remains a Markdown file tree. See the [layer and adapter architecture](docs/storage-layer.md) for local folders and future SharePoint integration.

Wiki content and source evidence are local data, excluded from Git in `wiki/`, `wiki-en/`, `source/`, and `sources/`. Supply your own Markdown folder. `make run` defaults to `wiki-en`; override it with `make run WIKI=/path/to/wiki`.

The web UI uses HTML, Pico CSS, and AlpineJS and runs on localhost through `wiki-worker ... web`.

## Discussion API

Discussions are durable SQLite records anchored to `project_id`, `document_path`, and `section_anchor`; they are not Markdown wiki content or contribution fields. Create them with `POST /api/discussions`, list/filter with `GET /api/discussions`, and reply with `POST /api/discussions/{id}/comments`.

Conflict resolution uses `POST /api/contribution/{id}/conflict` with `outcome` `keep_current`, `use_incoming`, or `merge`. The latter two create a new pending contribution against the current v2.

```text
POST /api/discussion                         createDiscussion
GET  /api/discussion/{proposalId}            getDiscussion
POST /api/discussion/{proposalId}/messages   addDiscussionMessage
POST /api/discussion/{proposalId}/hold       holdProposal
POST /api/discussion/{proposalId}/resolve    resolveDiscussion
```

Creation accepts `{proposal_id, actor, bundle_hash, reason}`. Messages and holds also require `discussion_version`; a message may include `agrees_with` to reference an earlier sequence. Resolution requires the configured reviewer and a `decision` of `resolved`, `rejected`, or `on_hold`. `resolved` releases the hold; the other outcomes retain it. Review decisions also bind both discussion versions returned by the contribution read. The existing `/api/contribution/{id}/discussion` endpoint remains for backward-compatible reviewer-mediated semantic-conflict records.

## Two workflows: contributor and reviewer

**Contributing — agent skill.** Agents discover and search files directly, obtain versions with `context`, read the sources, and create a `.contribution.md` file. They do not submit content through an HTTP API. See the [contribution convention](skills/wiki-knowledge-workflow/references/contribution.md).

**Reviewing — UI and skill.** Reviewers ingest files or bundles with `scan`, or import a `.contribution.md` file in the UI. `GET /api/contribution/ID` combines content, sources, status, and the exact artifact in one response. Review and publication use `/api/contribution/ID/review` and `/api/contribution/ID/publish`. See the [reviewer skill](skills/wiki-knowledge-workflow/references/reviewer.md).

The **Contribute** form creates a Markdown v3 file. Its **Scope and impact** table records `file | version | impact`; its **Sources** table records `file | version`. The worker resolves SHA-256 hashes from registered version snapshots, so these tables do not contain hashes. The first scope row identifies the primary file. Users can provide the complete content, replace a passage that occurs exactly once, or append content; the file always contains the complete resulting Markdown. Generation happens in the browser and does not add the file to the queue. The **Reviewer** form displays both tables alongside the content and pinned context.

Sources use `YYYYMMDD-N` versions based on UTC observation dates, immutable snapshots, and SHA-256. Freshness is checked at scan/import, approval, and publication. Agents assess content and make decisions; the system does not approve automatically. Older proposals without context appear as `unversioned`.

```sh
python -m wiki_worker.cli --state .wiki-worker --folder wiki-en --reviewer reviewer-agent web --port 8080
```

Check browser file generation with `node tests/test_ui_file.js` and the workflow with `python -m unittest discover -s tests -v`.

Run `make playground` for a disposable reviewer-workflow demo. It includes three contributions created from the same v1 (A is published as v2 while B and C retain concurrent-change evidence) and an explicit `X is blue` versus `X is red` semantic conflict. Follow [the reviewer demo runbook](docs/reviewer-demo-runbook.md). New discussions are reviewer-opened and anchored to a file/section. The demo does not modify the real wiki folder.
