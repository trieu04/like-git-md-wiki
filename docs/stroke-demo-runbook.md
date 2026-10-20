# Stroke wiki demo runbook

This demo uses the English wiki in `wiki-demo-stroke` and persistent worker state in `.wiki-worker/stroke-demo`.

Run:

```sh
make stroke-demo
```

Open `http://127.0.0.1:8093/`.

## Slack and continuous reviewer agent

With `SLACK_BOT_TOKEN` and `SLACK_CHANNEL` in `.env`, run these in separate terminals:

```sh
make stroke-demo-slack
make stroke-demo-agent-loop
```

The first process creates/reuses mapped Slack threads and polls them every 60 seconds. The second continuously dispatches a real ephemeral Codex reviewer when a new human `approve <reason>` or `reject <reason>` mention is ingested. The reviewer rereads the current artifact and evidence, applies an explicit review decision, posts its result back to the same Slack thread, and never publishes.

## Scenario 1: multiple contributors

Three contributors capture the same version of `stroke-basics.md`:

- `contribution-A-stroke-risk-factor`, by `contributor-a`, adds the supported high-blood-pressure statement. It is reviewed and published as the next version.
- `contribution-B-stroke-fast-detail`, by `contributor-b`, adds the FAST expansion from the old base.
- `contribution-C-stroke-prevention-habits`, by `contributor-c`, adds prevention examples from the old base.

The latter two remain pending and show concurrent-change evidence. A reviewer must compare base, current and proposed content, then request a fresh merged contribution; the worker does not merge automatically.

## Scenario 2: semantic conflict

`contribution-D-stroke-wait-30-minutes`, by `contributor-d`, proposes waiting before contacting emergency services. The frozen evidence explicitly says to contact emergency services immediately and not wait. The proposal is current but has an open reviewer-created semantic hold.

Approval must remain blocked. The reviewer may reject it with a concrete revision request. Do not publish this intentionally unsafe conflict example.

All source paths and versions are visible in the contribution view. The wiki is educational demo content, not medical advice.
