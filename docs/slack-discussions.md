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

When a contribution is observed against an older base after another version
has been published, the worker opens one idempotent `conflict-<proposal>` topic
for that file and mirrors its root discussion to Slack when Slack is configured.
The Slack channel and thread timestamp are retained in the local topic so
replies can be projected back into the canonical discussion store.

The Events API endpoint is `POST /api/slack/events`. Requests are authenticated
with Slack's signing secret and timestamped `v0` HMAC. It accepts URL
verification and `message`/`app_mention` events. Configure either a public
Events API request URL or Slack Socket Mode. Socket Mode is preferable for a
worker behind a firewall; the current adapter exposes the HTTP event handler,
while Socket Mode can forward the same event envelope to it.

Required Slack setup:

- `chat:write` to create root/reply messages.
- History access appropriate to the channel (`channels:history` or
  `groups:history`) if the worker needs to backfill replies with
  `conversations.replies`.
- Event subscriptions for channel/group message events (and `app_mention` if
  using an explicit bot command).
- `--slack-signing-secret` and `--slack-reviewer` (Slack user ID, not display
  name) when starting the web server.

Slack's `conversations.replies` is paginated and, for new non-Marketplace
installations, is rate-limited to one request per minute. Events are therefore
the primary ingestion path; `slack-sync` is a recovery/backfill command, not a
high-frequency poller.

References: [Events API](https://api.slack.com/events-api), [message events](https://api.slack.com/events/message/message_replied), [Socket Mode](https://api.slack.com/apis/connections/socket), [chat.postMessage](https://api.slack.com/methods/chat.postMessage), and [conversations.replies](https://api.slack.com/methods/conversations.replies).
