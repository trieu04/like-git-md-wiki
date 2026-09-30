"""Run a focused, disposable reviewer-workflow playground."""
import argparse
import os
import tempfile
from pathlib import Path

from wiki_worker.core import Worker
from wiki_worker.local import LocalFolderStorage
from wiki_worker.web import serve
from wiki_worker.slack import SlackDiscussion


def seed(root, reviewer):
    wiki = root / 'wiki'
    wiki.mkdir()
    (wiki / 'shared-guide.md').write_text(
        '# Shared guide\n\n'
        'This guide is based on version v1.\n\n'
        '## Overview\n\nThe service is available to all teams.\n\n'
        '## Installation\n\nInstall the stable package.\n\n'
        '## Support\n\nContact the service desk.\n', encoding='utf-8')
    (wiki / 'color-policy.md').write_text(
        '# Color policy\n\nX is blue.\n', encoding='utf-8')
    (wiki / 'color-standard.md').write_text(
        '# Approved color standard\n\n'
        'The approved production color for X is blue. '
        'This standard is effective from 2026-09-01.\n', encoding='utf-8')

    worker = Worker(root / 'state', LocalFolderStorage(wiki), reviewer, 'Demo owner')
    try:
        # Three contributions share the exact same v1.  A is reviewed and
        # published first.  B and C remain frozen against v1, so the worker
        # reports concurrent-change evidence without deciding conflict or
        # opening any discussion.
        shared = worker.agent_context('shared-guide.md', [])['context']
        worker.agent_propose({
            'id': 'contribution-a', 'target': 'shared-guide.md', 'submitter': 'author-a',
            'reason': 'Clarify service ownership in the overview. Based on shared-guide.md v1.',
            'content': ('# Shared guide\n\nThis guide is based on version v1.\n\n'
                        '## Overview\n\nThe Platform team owns the service, which is available to all teams.\n\n'
                        '## Installation\n\nInstall the stable package.\n\n'
                        '## Support\n\nContact the service desk.\n'),
            'sources': [], 'context': shared,
        })
        worker.agent_propose({
            'id': 'contribution-b', 'target': 'shared-guide.md', 'submitter': 'author-b',
            'reason': 'Add a verification step to the installation section. Based on the same v1 as A.',
            'content': ('# Shared guide\n\nThis guide is based on version v1.\n\n'
                        '## Overview\n\nThe service is available to all teams.\n\n'
                        '## Installation\n\nInstall the stable package and verify its checksum.\n\n'
                        '## Support\n\nContact the service desk.\n'),
            'sources': [], 'context': shared,
        })
        worker.agent_propose({
            'id': 'contribution-c', 'target': 'shared-guide.md', 'submitter': 'author-c',
            'reason': 'Add the support response window. Based on the same v1 as A and B.',
            'content': ('# Shared guide\n\nThis guide is based on version v1.\n\n'
                        '## Overview\n\nThe service is available to all teams.\n\n'
                        '## Installation\n\nInstall the stable package.\n\n'
                        '## Support\n\nContact the service desk. Expect a response within one business day.\n'),
            'sources': [], 'context': shared,
        })
        a_view = worker.preview('contribution-a', reviewer)
        worker.review('contribution-a', reviewer, a_view, True,
                      'The ownership clarification is internally consistent and ready for the demo.')
        worker.publish('contribution-a')

        # This proposal contradicts both the current page and its declared
        # evidence while the hashes remain fresh.  Only the reviewer records
        # the semantic-conflict conclusion.
        colors = worker.agent_context('color-policy.md', ['color-standard.md'])['context']
        worker.agent_propose({
            'id': 'color-red', 'target': 'color-policy.md', 'submitter': 'color-author',
            'reason': 'Change the stated color of X from blue to red.',
            'content': '# Color policy\n\nX is red.\n',
            'sources': [], 'context': colors,
        })
        color_view = worker.contribution('color-red')
        worker.discuss(
            'color-red', reviewer, color_view['bundle_hash'], color_view['discussion_version'], 'open',
            'Question: What is the approved production color for X?\n'
            'Claim A: The current page says "X is blue."\n'
            'Claim B: Contribution color-red says "X is red."\n'
            f'Scope: production color policy, effective from 2026-09-01.\n'
            f'Evidence A: color-standard.md@{colors["sources"][0]["version"]} says the approved color is blue.\n'
            'Evidence B: no versioned evidence supporting red was declared.\n'
            'Alternatives: retain blue, provide authoritative evidence for red, or narrow the claim.\n'
            'Objections: the proposal reason alone is not evidence.\n'
            'Outcome: no decision; semantic conflict remains open.\n'
            'Next step: obtain an approved standard that explicitly changes X to red.')
    finally:
        worker.db.close()
    return wiki


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8080)
    parser.add_argument('--reviewer', default='reviewer-agent')
    parser.add_argument('--slack-token', default=os.getenv('SLACK_BOT_TOKEN'))
    parser.add_argument('--slack-channel', default=os.getenv('SLACK_CHANNEL') or os.getenv('SLACK_CHANEL'))
    parser.add_argument('--slack-signing-secret', default=os.getenv('SLACK_SIGNING_SECRET'))
    parser.add_argument('--slack-reviewer', default=os.getenv('SLACK_REVIEWER'))
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='wiki-semantic-playground-') as folder:
        root = Path(folder)
        wiki = seed(root, args.reviewer)
        print('Reviewer workflow demo is ready:')
        print('- contribution-a is published as v2; contribution-b and contribution-c retain v1 evidence.')
        print('- color-red has an open semantic conflict: "X is blue" versus "X is red".')
        print(f'Open http://{args.host}:{args.port}/ and follow docs/reviewer-demo-runbook.md.')
        print('The playground is disposable and does not modify wiki-en.')
        slack = None
        if args.slack_token and args.slack_channel:
            slack = SlackDiscussion(args.slack_token, args.slack_channel)
            print(f'Slack discussion sync enabled for channel {args.slack_channel}.')
        serve(args.host, args.port, root / 'state', wiki, None, args.reviewer, 'Demo owner', slack,
              args.slack_signing_secret, args.slack_reviewer)


if __name__ == '__main__':
    main()
