# Implementation plan

The Python/SQLite fixture workflow for steps 2–3 is implemented; see [runtime](runtime.md). The live SharePoint spike and pilot still require a tenant. Work through the four steps in order, without scaffolding unused capabilities in advance.

Prioritize a small working flow. Pause publication with an uncertain outcome for manual investigation; do not build a general automatic recovery mechanism yet.

## Step 1 — SharePoint spike

- Write scripts to test reading/uploading and conditional update/create in a test folder. Prove that content bytes and ETag belong to the same version, including when a file changes between reads.
- Check submitter identity, reviewer authentication, and permissions protecting wiki/history.
- Check Markdown rendering and review status in the current reading channel.
- Record results and API limitations without committing secrets.

Complete when authentication and overwrite protection are demonstrated. If no tenant is available, use fixtures for the next step and explicitly record that integration remains unverified.

## Step 2 — Submit and review

- Build a small Python program with SQLite and `scan`, `review`, and `status` commands. Share a process lock across state changes from this step onward.
- Parse manifests, validate paths/hashes/file limits, freeze bundles, and handle duplicate proposal IDs.
- Display the diff, sources, reason, and final file with its status block. Store decisions bound to bundle/artifact hashes and authenticated identities.
- Block self-review and payload changes after ingestion.

Complete when the designated reviewer can review a proposal and every retry still refers to exactly one bundle.

## Step 3 — Publish and recover

- Add `publish` using the shared process lock. Persist target, artifact hash, and write conditions before the remote write, and use the conditional operation verified by the spike.
- Publish the exact approved artifact. Retain base/proposed/artifact hashes and the remote result; finish history before reporting `published`.
- On restart, inspect incomplete writes and block other publications to the same target while the outcome remains unknown. Other files can proceed. Record operator evidence before unblocking. A matching hash is insufficient evidence, and history failures after writing must not trigger another wiki upload.
- Add cron, backup, and instructions for handling stale content and drift.

Complete when tests prove that only one of two proposals with the same base can publish to the same file; crashes after remote writes do not duplicate publication; uncertain writes remain blocked; and unexpected remote changes are not overwritten. Published artifacts must match the approved bytes. Restoration through a new proposal must not retain old review labels or duplicate status blocks.

Test two cases separately: changes between content and metadata reads must not produce an invalid write condition; an uncertain write must block other proposals to the same target across restarts while leaving other targets usable.

## Step 4 — Pilot

- Configure permissions, import documents with unreviewed labels, and run realistic scenarios.
- Test expired tokens, throttling, denied permissions, and backup/restore.
- Record queue age, correction time, and sample-check errors manually.
- Let the designated owner decide whether to expand based on the results. Do not expand while review is already a bottleneck.

Focus testing on permissions, versions, idempotency, and crash recovery. Use real SQLite, a fake remote for fault injection, and live SharePoint checks in a test folder. The initial plan did not require an API server, UI, general benchmarks, dashboards, or tests for every helper; the current runtime also includes a local reviewer UI/API.
