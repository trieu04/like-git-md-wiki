# For agent contributor

Discover relevant Markdown files directly in the configured wiki folder using file listing, `rg`, and reads. Paths are relative to that folder. Sources must be inside the configured storage before they can be versioned.

## Get versions before drafting

Use the same state, storage and reviewer configuration as the running reviewer:

```sh
python -m wiki_worker.cli --state .wiki-worker --folder wiki --reviewer reviewer-agent \
  context index.md --source nguon-va-bao-tri.md
```

Read the returned content, `version`, `hash` and `captured_at`. Use the returned versions for the primary file, sources and any file in scope. The snapshots are registered in worker state; use the same state for scan/review. No author HTTP request or separate context file is needed.

## Markdown contribution file

Create `ID.contribution.md`. It begins with readable metadata:

```markdown
# Wiki contribution

| Field | Value |
| --- | --- |
| Format | wiki-contribution-v3 |
| Boundary | wc-example-unique-token |
| ID | update-policy |
| Base SHA-256 | 64-character hash |
| Proposed SHA-256 | 64-character hash |
| Author | author-agent |
| Reason | Claim and evidence |

## Scope and impact files

| File | Version | Impact |
| --- | --- | --- |
| policy.md | 20260908-1 | Change the policy period |
| docs/guide.md | 20260908-2 | Update the related instructions |

## Sources

| File | Version |
| --- | --- |
| sources/handbook.md | 20260908-3 |
```

The first scope row identifies the primary file whose content is changed. Add each related or affected file with its observed version and a concrete impact. Add every versioned evidence document to **Sources**. The worker resolves the SHA-256 from its registered snapshot for each `file | version` pair; do not add a hash column to either table. It rejects unknown versions, changed snapshots and conflicting versions for the same file. If there are no other scope files or sources, keep the primary row and the empty Sources table. Escape `|` in metadata and impact cells as `\|` and line breaks as `<br>`.

Write the proposed and base content as plain UTF-8 Markdown, in that order, separated by visible reserved breaks:

```markdown
## Proposed content

--- wc-example-unique-token:proposed ---

Proposed Markdown goes here.

--- wc-example-unique-token:base ---

## Base content

Exact original Markdown goes here.

--- wc-example-unique-token:end ---
```

Choose a Boundary matching `wc-[a-z0-9-]{1,200}` which does not occur anywhere in either payload. Use that exact token in all three breaks. Ordinary Markdown rules, headings and old contribution markers inside content are not delimiters. Do not encode or escape the payloads. The wrapper adds exactly two LF characters before and after each payload, and one LF after the end break; these framing characters are not payload bytes. Preserve the payload's own trailing newlines and CRLF bytes separately, including when there is no final newline. `Base SHA-256` and `Proposed SHA-256` hash the exact payloads, excluding framing. Do not invent versions or hashes, and do not include an old review banner in proposed content.

The UI **Tạo file đóng góp** provides named fields and generates this Markdown locally. An agent may generate it directly. Deliver it to the reviewer/operator, who ingests it with:

```sh
python -m wiki_worker.cli --state .wiki-worker --folder wiki --reviewer reviewer-agent \
  scan contributions/update-policy.contribution.md --submitter author-agent
```

To ingest every `*.contribution.md` directly inside an incoming directory, pass the directory instead:

```sh
python -m wiki_worker.cli --state .wiki-worker --folder wiki --reviewer reviewer-agent \
  scan wiki/contributions --submitter author-agent
```

One verified submitter identity applies to every file in that scan. Existing bundle directories containing
`proposal.ready.json` remain supported.

The verified submitter comes from the caller, not the Author table cell. Scan validates registered versions, freezes the contribution as pending, and does not approve or publish. If context changed, reread it, reassess the content and use a new ID.

Optional metadata rows `Author name`, `Author role`, `Author expert`, and `Author metadata source` are preserved as `author_metadata` (`name`, `role`, `expert`, `metadata_source`) in the frozen manifest and reviewer response. `expert` describes the author's subject expertise. These are author declarations, not verified credentials; they never replace the verified submitter. Bundles may supply the same string fields in `author_metadata`. Declare and capture any provenance document used as evidence. For a merged revision, include predecessor contribution IDs and the resolution rationale in Reason; follow [merge-conflicts.md](merge-conflicts.md).

The UI can compose the proposed content by replacing one uniquely occurring passage or appending text; it still writes the complete final Markdown payload above. The existing directory bundle (`base.md`, `proposed.md`, `proposal.ready.json` written last) remains supported. Its manifest may carry the exact context object returned by the CLI. Each manifest/base/proposed payload is limited to 1 MiB; the Markdown wrapper is limited to 4 MiB plus 64 KiB. Only plain Markdown `wiki-contribution-v3` files are accepted.
