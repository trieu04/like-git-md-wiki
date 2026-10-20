# Slack discussion integration

The worker opens one Slack thread for each file/section discussion. The root
message contains the discussion ID, file and section anchor; replies are
projected into the local SQLite discussion record with the Slack message
timestamp as an idempotency key.

Discussion completion is explicit. The worker never treats inactivity as
completion. A participant or automation sends `close <reason>` as a reply (or
calls `POST /api/discussions/{id}/close`). The worker marks the discussion as
resolved, posts the outcome, and mentions the configured reviewer once. The
reviewer still makes the content decision through the normal review workflow;
Slack only activates/alerts the reviewer.

The worker writes the tracked contribution authors of the topic's document and
related files into the thread as plain `@author` references. Those mentions
implicitly identify the expected handlers, and `decision_owners` names one or
more representatives expected to decide and close. This is deliberately non-binding:
wiki author names are not mapped to Slack usernames or user IDs, so the worker
does not use them as an authorization check. For a legacy file without tracked
author data, the topic author is the fallback reference.

When an agent reviewer cannot decide, a human can mention the bot in the
discussion thread with `approve <reason>` or `reject <reason>`. The Events API
records the exact Slack actor, decision, reason and message timestamp, then
forwards that request to the configured Slack reviewer. The same request is
returned as `reviewer_decision_requests` by `GET /api/contribution/{id}` so an
agent reviewer can consume it. This handoff never changes contribution state:
the configured reviewer must still submit the normal review request, and
publication remains separate.

When a contribution is observed against an older base after another version
has been published, the worker opens one idempotent `conflict-<proposal>` topic
for that file and mirrors its root discussion to Slack when Slack is configured.
The Slack channel and thread timestamp are retained in the local topic so
replies can be projected back into the canonical discussion store.

The Events API endpoint is `POST /api/slack/events`. When a signing secret is
configured, requests are authenticated with Slack's timestamped `v0` HMAC. A
localhost demo may omit the signing secret and accept unsigned events; do not
expose that mode on an untrusted network. The endpoint accepts URL verification
and `message`/`app_mention` events. Configure either a public Events API request
URL or Slack Socket Mode. Socket Mode is preferable for a worker behind a
firewall; the current adapter exposes the HTTP event handler, while Socket Mode
can forward the same event envelope to it.

Required Slack setup:

- `chat:write` to create root/reply messages.
- History access appropriate to the channel (`channels:history` or
  `groups:history`) if the worker needs to backfill replies with
  `conversations.replies`.
- Event subscriptions for channel/group message events (and `app_mention` if
  using an explicit bot command).
- `--slack-signing-secret` for authenticated Events API delivery; omit only for
  a localhost demo.
- `--slack-reviewer` (Slack user ID, not display name) is optional; without it,
  the decision request is recorded and forwarded without mentioning a reviewer.

Slack's `conversations.replies` is paginated and, for new non-Marketplace
installations, is rate-limited to one request per minute. Events are therefore
the primary ingestion path; `slack-sync` is a recovery/backfill command, not a
high-frequency poller.

References: [Events API](https://api.slack.com/events-api), [message events](https://api.slack.com/events/message/message_replied), [Socket Mode](https://api.slack.com/apis/connections/socket), [chat.postMessage](https://api.slack.com/methods/chat.postMessage), and [conversations.replies](https://api.slack.com/methods/conversations.replies).
