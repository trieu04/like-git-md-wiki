# Merge and conflict logic

## Classify before deciding

| Situation | Meaning | Reviewer action |
| --- | --- | --- |
| Target and sources current | Frozen references still match observed storage | Assess evidence and exact artifact using approval rules |
| Target stale | Another edit changed the target since the author's base | Compare base, current and proposed; require a new contribution |
| Source stale | Evidence or related scope file changed | Reread old and current evidence, reassess affected claims; require new context and contribution |
| Text conflict | Both edits replace/delete the same passage incompatibly | Resolve using evidence and author metadata; no automatic winner |
| Semantic conflict | Edits contradict each other even in different passages | Resolve the claim and update all affected passages in a new contribution |
| Evidence insufficient | No supported resolution is available | Leave pending with missing evidence identified, or reject with reasons |
| Write outcome unknown | Worker has `phase=writing` and uncertain receipt | Use the runtime recovery procedure; do not treat this as a text conflict |

`stale` is a freshness result, not proof of a text conflict. The worker reports freshness and guards writes; the reviewer classifies text/semantic conflicts. A pending contribution can have stale context without its lifecycle state changing. Approval then fails. A contribution already approved becomes `stale` if publication detects a changed base/context or conditional-write conflict. An old file imported after the change is refused at ingestion.

## Three-way merge procedure

1. Read `/api/contribution/ID` for frozen base B, proposed P, evidence, metadata and exact artifact. Read `/api/wiki/document?path=PATH` for current C and `/api/wiki/versions?path=PATH` for intervening contributions and decisions. Use `/api/wiki/version` to inspect exact historical snapshots; URL-encode parameters.
2. Compare B→P (author intent) and B→C (already published work). Ignore the reserved review banner when interpreting claims, but preserve exact B bytes for hashes. Classify overlap and semantic contradictions, including changes to sources.
3. Preserve compatible edits from both sides. For incompatible claims, apply the reviewer evidence/metadata rules. Do not choose last writer, higher title, or expert label automatically. If unresolved, record the disputed passages, source versions and missing evidence; do not publish.
4. If assigned to author the resolution, capture and read fresh context using the context CLI. Build a new file/bundle with a new ID, C as its exact base, the merged full body without an old review banner, and all evidence/scope references. In Reason, link predecessor contribution IDs, base/current versions, retained/replaced claims and the evidence for each conflict decision. Otherwise request that concrete revision from the author.
5. The resolution author and its configured reviewer must be distinct. Review the new artifact again. Do not mutate the old frozen contribution or reuse its approval. Publish only within the assigned workflow. If the target changes again, repeat the comparison against the new current version; never merely update labels or force an overwrite.

## Two users editing one file

Both users capture `policy.md` at `20260909-1`. Their contributions A and B are imported. A is reviewed and published; the worker saves the exact published artifact as `20260909-2`. B still targets `20260909-1`, so its context is stale even if the changes touch separate paragraphs. If B was approved before A published, its publication returns `stale`; otherwise approval is blocked. Compare B's base/proposed with `20260909-2`. For compatible changes create B2 based on `20260909-2`, review and publish to `20260909-3`. For overlapping contradictory changes, settle the claim from evidence first or leave unresolved.

Versions are `YYYYMMDD-N`: the sequence increments for newly recorded content on the same UTC day and restarts at 1 on a new day. Publish retries do not create another change. History retains base/proposed bytes through the contribution endpoint, exact published snapshots through the version endpoint, plus decisions and receipts. Historical reads do not observe current storage. External edits are recorded only when observed; this is not a complete external edit log or an atomic snapshot of multiple files.

## Uncertain writes

`resolve` in the CLI resolves storage write outcomes only, not merge conflicts. Consult `docs/runtime.md` and `python -m wiki_worker.cli resolve --help`. A `written` resolution requires a verifiable operation receipt matching the prepared write; matching visible content alone is insufficient. Preserve evidence in the resolution record. Do not retry a blocked target or invent a receipt.
