# Microsoft Teams discussion integration

The Teams adapter mirrors each wiki discussion to a root message and replies in
one Microsoft Teams channel. It uses Microsoft Graph and stores only the thread
coordinates in worker state; the canonical discussion and decision records stay
in SQLite. A Teams reply beginning with `approve <reason>` or `reject <reason>`
creates an advisory reviewer-decision request. It never approves, rejects, or
publishes a contribution by itself.

A reply beginning with `close` resolves the discussion topic. The sender ID is
recorded for attribution only: it is not compared with the wiki `author`,
`resolve_assignees`, or `decision_owners`. Those identities are coordination
hints and are not an authorization boundary because wiki and Microsoft Entra
identities are not mapped. Closing a topic does not review or publish the
associated contribution; those actions still require the configured reviewer.

Configure the adapter with an existing Graph access token, team ID, channel ID,
and a random webhook `clientState` secret. `--teams-reviewer` is the Microsoft
Entra user object ID that should receive a real Teams mention:

```sh
cp .env.example .env
# Fill in the TEAMS_* values, then load them into the current shell.
set -a; . ./.env; set +a

python -m wiki_worker.cli \
  --state .wiki-worker --folder wiki-en --reviewer reviewer-agent \
  --teams-token "$TEAMS_GRAPH_TOKEN" \
  --teams-team "$TEAMS_TEAM_ID" \
  --teams-channel "$TEAMS_CHANNEL_ID" \
  --teams-client-state "$TEAMS_CLIENT_STATE" \
  --teams-reviewer "$TEAMS_REVIEWER_ID" \
  web --port 8080
```

The worker does not acquire, persist, or refresh the Graph token. Normal message
sending uses delegated `ChannelMessage.Send`; Microsoft documents application
permission for this endpoint only for migration. Reply backfill needs delegated
`ChannelMessage.Read.All`, or an applicable application read permission such as
resource-specific `ChannelMessage.Read.Group`. See [send channel
messages](https://learn.microsoft.com/graph/api/channel-post-messages), [send a
reply](https://learn.microsoft.com/graph/api/chatmessage-post-replies), and [list
replies](https://learn.microsoft.com/graph/api/chatmessage-list-replies).

## Change notifications

Create a Microsoft Graph subscription for:

```text
/teams/{team-id}/channels/{channel-id}/messages
```

Set `includeResourceData` to `false`, set its notification URL to the public
HTTPS URL ending in `/api/teams/events`, and set the subscription `clientState`
to the same secret passed as `--teams-client-state`. The endpoint returns
Graph's validation token as plain text and ignores notifications whose
`clientState` does not match. Basic notifications are resolved through Graph
before ingestion. Encrypted rich-notification payloads are not decrypted by
this adapter. See [Teams
message change notifications](https://learn.microsoft.com/graph/teams-changenotifications-chatmessage)
and [webhook delivery and validation](https://learn.microsoft.com/graph/change-notifications-delivery-webhooks).

Graph subscriptions expire and must be renewed by the deployment. Production
deployments should queue notifications and return `202 Accepted` within Graph's
delivery deadline; this small localhost worker processes them synchronously and
is not a production webhook service. Use `teams-sync PROPOSAL_ID` for manual
recovery/backfill.
