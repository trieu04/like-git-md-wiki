import argparse
import json
import sys
from pathlib import Path

from .common import Conflict, Invalid, read_file, target_path
from .core import Worker
from .fixture import FixtureRemote
from .local import LocalFolderStorage
from .web import serve


def main():
    parser = argparse.ArgumentParser(description='Review layer for Markdown wikis; local folder or test fixture')
    parser.add_argument('--state', default='.wiki-worker')
    storage = parser.add_mutually_exclusive_group(required=True)
    storage.add_argument('--folder', help='published Markdown wiki root; all writers must use the adapter')
    storage.add_argument('--fixture', help='SQLite test transport')
    parser.add_argument('--reviewer', required=True, help='reviewer ID in the trusted local execution environment')
    parser.add_argument('--owner', default='Pilot owner')
    parser.add_argument('--slack-token', help='Slack bot token (discussion transport)')
    parser.add_argument('--slack-channel', help='Slack channel ID for discussion threads')
    parser.add_argument('--slack-signing-secret', help='Slack Events API signing secret')
    parser.add_argument('--slack-reviewer', help='Slack user ID to mention when a discussion is explicitly closed')
    parser.add_argument('--discord-token', help='Optional Discord bot token')
    parser.add_argument('--discord-channel', help='Optional Discord channel ID')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('list', help='list Markdown documents')
    show = sub.add_parser('show', help='read a Markdown document')
    show.add_argument('target')
    propose = sub.add_parser('propose', help='capture current base and propose Markdown content')
    propose.add_argument('id')
    propose.add_argument('target')
    propose.add_argument('file')
    propose.add_argument('--submitter', required=True)
    propose.add_argument('--reason', required=True)
    propose.add_argument('--source', action='append', default=[])
    context = sub.add_parser('context', help='capture versioned target and source context for an agent')
    context.add_argument('target')
    context.add_argument('--source', action='append', default=[])
    sub.add_parser('agent-instructions', help='show author and reviewer agent protocol as JSON')
    agent_propose = sub.add_parser('agent-propose', help='submit agent JSON using previously read context')
    agent_propose.add_argument('file')
    scan = sub.add_parser('scan')
    scan.add_argument('path')
    scan.add_argument('--submitter', required=True, help='identity asserted by the trusted local caller')
    review = sub.add_parser('review')
    review.add_argument('id')
    review.add_argument('--actor', required=True, help='identity asserted by the trusted local caller')
    review.add_argument('--reason', required=True)
    review.add_argument('--reject', action='store_true')
    discuss = sub.add_parser('discuss', help='record a semantic dispute, comment or resolution')
    discuss.add_argument('id')
    discuss.add_argument('--actor', required=True)
    discuss.add_argument('--action', required=True, choices=['open', 'comment', 'resolve', 'reopen'])
    discuss.add_argument('--reason', required=True)
    discuss.add_argument('--resolution-kind', choices=['supported', 'scoped', 'attributed', 'not_a_conflict'])
    discuss.add_argument('--related', action='append', default=[])
    publish = sub.add_parser('publish')
    publish.add_argument('id')
    sub.add_parser('status')
    sync = sub.add_parser('slack-sync', aliases=['discord-sync'], help='collect replies into the canonical discussion store')
    sync.add_argument('id')
    resolve = sub.add_parser('resolve')
    resolve.add_argument('id')
    resolve.add_argument('--actor', required=True)
    resolve.add_argument('--outcome', required=True, choices=['written', 'not-written'])
    resolve.add_argument('--evidence', required=True)
    resolve.add_argument('--receipt')
    backup = sub.add_parser('backup')
    backup.add_argument('destination')
    seed = sub.add_parser('fixture-put', help='simulate an external edit; fixture setup only')
    seed.add_argument('target')
    seed.add_argument('file')
    sub.add_parser('fixture-receipts')
    web = sub.add_parser('web', help='serve the local web UI')
    web.add_argument('--host', default='127.0.0.1')
    web.add_argument('--port', default=8080, type=int)
    args = parser.parse_args()
    try:
        if args.command.startswith('fixture-') and not args.fixture:
            raise Invalid('fixture commands require --fixture')
        remote = LocalFolderStorage(args.folder) if args.folder else FixtureRemote(args.fixture)
        transport = None
        if args.slack_token or args.slack_channel:
            if not args.slack_token or not args.slack_channel:
                raise Invalid('--slack-token and --slack-channel must be used together')
            from .slack import SlackDiscussion
            transport = SlackDiscussion(args.slack_token, args.slack_channel)
        elif args.discord_token or args.discord_channel:
            if not args.discord_token or not args.discord_channel:
                raise Invalid('--discord-token and --discord-channel must be used together')
            from .discord import DiscordDiscussion
            transport = DiscordDiscussion(args.discord_token, args.discord_channel)
        worker = Worker(args.state, remote, args.reviewer, args.owner, slack=transport)
        if args.command == 'list':
            print(json.dumps(remote.list_markdown(), indent=2, ensure_ascii=False))
        elif args.command == 'show':
            document = remote.read(target_path(args.target))
            if document is None:
                raise Invalid('document not found')
            sys.stdout.buffer.write(document['content'])
        elif args.command == 'propose':
            print(worker.propose(args.id, args.target, read_file(Path(args.file)),
                                 args.submitter, args.reason, args.source))
        elif args.command == 'context':
            print(json.dumps(worker.agent_context(args.target, args.source), indent=2, ensure_ascii=False))
        elif args.command == 'agent-instructions':
            from .context import INSTRUCTIONS
            print(json.dumps(INSTRUCTIONS, indent=2, ensure_ascii=False))
        elif args.command == 'agent-propose':
            from .common import parse
            data = parse(read_file(Path(args.file)))
            if not isinstance(data, dict):
                raise Invalid('agent proposal must be an object')
            print(worker.agent_propose(data))
        elif args.command == 'scan':
            result = worker.scan(args.path, args.submitter)
            print(json.dumps(result, ensure_ascii=False) if isinstance(result, list) else result)
        elif args.command == 'review':
            preview = worker.preview(args.id, args.actor)
            print('Reason:', preview['reason'])
            print('Sources:', json.dumps(preview['sources'], ensure_ascii=False))
            print('Context:', json.dumps(preview['context_documents'], ensure_ascii=False))
            print('Context status:', json.dumps(preview['context_status'], ensure_ascii=False))
            print('Semantic discussion:', json.dumps(preview['semantic_discussion'], ensure_ascii=False))
            print('Disputed:', preview['disputed'])
            print(preview['diff'])
            print('Exact final artifact:\n' + preview['artifact'].decode())
            # No process lock held while a human reads and confirms.
            action = 'reject' if args.reject else 'approve'
            if input(f'Type {action} to confirm: ').strip() != action:
                print('No decision saved.')
                return
            worker.review(args.id, args.actor, preview, not args.reject, args.reason)
            print('rejected' if args.reject else 'approved')
        elif args.command == 'discuss':
            proposal = worker.contribution(args.id)
            result = worker.discuss(
                args.id, args.actor, proposal['bundle_hash'], proposal['discussion_version'],
                args.action, args.reason, args.resolution_kind, args.related)
            print(json.dumps(result, indent=2, ensure_ascii=False))
        elif args.command == 'publish':
            print(worker.publish(args.id))
        elif args.command == 'status':
            print(json.dumps(worker.status(), indent=2))
        elif args.command in ('discord-sync', 'slack-sync'):
            method = worker.sync_discord_discussion if args.command == 'discord-sync' else worker.sync_slack_discussion
            print(json.dumps(method(args.id), ensure_ascii=False))
        elif args.command == 'resolve':
            worker.resolve(args.id, args.actor, args.outcome, args.evidence, args.receipt)
            print('Resolution saved.')
        elif args.command == 'backup':
            worker.backup(args.destination)
            print('Backup complete (includes frozen bundles, artifacts and history).')
        elif args.command == 'fixture-put':
            target = target_path(args.target)
            old = remote.read(target)
            print(json.dumps(remote.write(target, read_file(Path(args.file)),
                                          None if old is None else [old['item'], old['version']])))
        elif args.command == 'fixture-receipts':
            print(json.dumps([dict(r) for r in remote.db.execute('SELECT * FROM writes')], indent=2))
        elif args.command == 'web':
            worker.db.close()
            serve(args.host, args.port, args.state, args.folder, args.fixture,
                  args.reviewer, args.owner, transport, args.slack_signing_secret,
                  args.slack_reviewer)
    except (Invalid, Conflict, OSError, EOFError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
