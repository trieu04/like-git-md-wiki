# Plan

## 1. Verify the minimum prerequisites

Choose a test folder and designated reviewer. Check Markdown reading channels, wiki/history write permissions, submitter and reviewer identities, and conditional update/create behavior on SharePoint. Record evidence from the APIs tested. Do not publish to live storage without verified overwrite protection and authentication.

## 2. Build one complete workflow

Submit a single-file bundle, inspect its diff and final file, review it, publish conditionally, and retain history. Test retries and crashes within this workflow. Pause writes with uncertain outcomes for the operator to investigate. Do not automate every recovery scenario or expand into a graph yet.

## 3. Run a small pilot

Use a few documents with real people and agents. Manually measure proposal waiting time, correction time, and errors that escape review. Rehearse correcting and restoring incorrect content and restarting the worker.

## 4. Expand only in response to observed problems

- Growing review backlog: improve the review process or add reviewers before adding agents.
- Frequent changes spanning multiple files: consider multi-file bundles.
- Reviews often forgotten: add reminders or due dates.
- Contradictions in specific passages: try claim or section assessment in that scope.

Each feature must identify the real problem, the simplest way to address it, and its validation criteria. Long-term reference documents do not automatically become MVP requirements.
