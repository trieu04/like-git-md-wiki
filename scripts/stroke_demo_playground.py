"""Build and serve a persistent, simple stroke-wiki workflow demo."""
import argparse
import os
import re
import threading
import time
from pathlib import Path

from wiki_worker.common import digest
from wiki_worker.core import Worker
from wiki_worker.local import LocalFolderStorage
from wiki_worker.slack import SlackDiscussion, SlackError
from wiki_worker.web import serve


SEED_FILES = {
    'index.md': (
        '# Stroke demo wiki\n\nThis small English-language wiki supports a reviewer-workflow demonstration.\n\n'
        '- [Stroke basics](stroke-basics.md)\n- [Emergency action](emergency-action.md)\n'
        '- [Emergency-response evidence](sources/emergency-guidance.md)\n'
        '- [Prevention evidence](sources/prevention-guidance.md)\n\n'
        'The content is for workflow demonstration and general education only. It is not medical advice. '
        'In a possible stroke emergency, contact local emergency services immediately.\n'),
    'stroke-basics.md': (
        '# Stroke basics\n\nA stroke happens when blood flow to part of the brain is blocked or when a blood vessel in the brain bursts.\n\n'
        '## Recognition\n\nSudden face weakness, arm weakness, or speech difficulty can be warning signs of stroke.\n\n'
        '## Action\n\nStroke is a medical emergency. Contact local emergency services immediately when stroke is suspected.\n\n'
        '## Prevention\n\nSome stroke risk factors can be reduced through appropriate health care and healthy habits.\n'),
    'emergency-action.md': (
        '# Emergency action for possible stroke\n\nUse the FAST reminder: Face drooping, Arm weakness, Speech difficulty, Time to contact emergency services.\n\n'
        'If stroke is suspected, contact local emergency services immediately. Do not wait for symptoms to improve.\n'),
    'sources/emergency-guidance.md': (
        '# Demo evidence: emergency response\n\nFor this workflow demo, the approved emergency-response statement is:\n\n'
        '> Sudden face drooping, arm weakness, or speech difficulty may indicate stroke. Contact local emergency services immediately and note when symptoms began. Do not wait to see whether symptoms improve.\n\n'
        'This internal demo evidence summarizes the FAST public-health message. It is evidence for the demo, not a substitute for local clinical guidance.\n\n'
        'External reference: CDC, “Signs and Symptoms of Stroke,” https://www.cdc.gov/stroke/signs-symptoms/\n'),
    'sources/prevention-guidance.md': (
        '# Demo evidence: stroke prevention\n\nFor this workflow demo, the approved prevention statements are:\n\n'
        '- High blood pressure is an important modifiable risk factor for stroke.\n'
        '- People should discuss blood-pressure management and individual risk factors with a qualified health professional.\n'
        '- Avoiding tobacco, being physically active when appropriate, and following an appropriate eating pattern can support cardiovascular health.\n\n'
        'This internal demo evidence is educational and does not prescribe treatment.\n\n'
        'External reference: CDC, “Prevent Stroke: What You Can Do,” https://www.cdc.gov/stroke/prevention/\n'),
}


def write_seed_wiki(wiki):
    wiki = Path(wiki)
    for relative, content in SEED_FILES.items():
        path = wiki / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')


def contribution_file(ident, author, reason, target, context, proposed, base):
    boundary = 'wc-' + ident.lower()
    source_rows = '\n'.join(
        f'| {ref["path"]} | {ref["version"]} |' for ref in context['sources'])
    return f'''# Wiki contribution

| Field | Value |
| --- | --- |
| Format | wiki-contribution-v3 |
| Boundary | {boundary} |
| ID | {ident} |
| Base SHA-256 | {digest(base.encode())} |
| Proposed SHA-256 | {digest(proposed.encode())} |
| Author | {author} |
| Reason | {reason} |

## Scope and impact files

| File | Version | Impact |
| --- | --- | --- |
| {target} | {context['target']['version']} | {reason} |

## Sources

| File | Version |
| --- | --- |
{source_rows}

## Proposed content

--- {boundary}:proposed ---

{proposed}

--- {boundary}:base ---

## Base content

{base}

--- {boundary}:end ---
'''


def initialize(wiki, state, reviewer='reviewer-agent'):
    """Create frozen contribution files, ingest them, and establish demo states."""
    wiki, state = Path(wiki), Path(state)
    contributions = wiki / 'contributions'
    contributions.mkdir(exist_ok=True)
    worker = Worker(state, LocalFolderStorage(wiki), reviewer, 'Stroke demo owner')
    try:
        basics = worker.agent_context(
            'stroke-basics.md', ['sources/emergency-guidance.md',
                                 'sources/prevention-guidance.md'])
        base = basics['documents'][0]['content']
        emergency_ref, prevention_ref = basics['context']['sources']

        proposals = [
            ('contribution-A-stroke-risk-factor', 'contributor-a',
             'Add the evidence-supported high-blood-pressure risk statement.',
             basics['context']['target'], [prevention_ref],
             base.replace(
                 'Some stroke risk factors can be reduced through appropriate health care and healthy habits.\n',
                 'High blood pressure is an important modifiable risk factor for stroke. Some stroke risk factors can be reduced through appropriate health care and healthy habits.\n')),
            ('contribution-B-stroke-fast-detail', 'contributor-b',
             'Expand the FAST reminder using the approved emergency-response evidence.',
             basics['context']['target'], [emergency_ref],
             base.replace(
                 'Sudden face weakness, arm weakness, or speech difficulty can be warning signs of stroke.\n',
                 'Use FAST to remember warning signs: Face drooping, Arm weakness, Speech difficulty, and Time to contact emergency services.\n')),
            ('contribution-C-stroke-prevention-habits', 'contributor-c',
             'Add evidence-supported examples of healthy prevention habits.',
             basics['context']['target'], [prevention_ref],
             base.replace(
                 'Some stroke risk factors can be reduced through appropriate health care and healthy habits.\n',
                 'Some stroke risk factors can be reduced through appropriate health care and healthy habits, including avoiding tobacco and being physically active when appropriate.\n')),
        ]

        for ident, author, reason, target_ref, source_refs, proposed in proposals:
            context = {'target': target_ref, 'sources': source_refs}
            path = contributions / f'{ident}.contribution.md'
            path.write_text(contribution_file(
                ident, author, reason, 'stroke-basics.md', context, proposed, base),
                encoding='utf-8')
            worker.scan(path, author)

        first = worker.preview('contribution-A-stroke-risk-factor', reviewer)
        worker.review('contribution-A-stroke-risk-factor', reviewer, first, True,
                      'Checked prevention evidence and exact artifact; the risk-factor statement is supported.')
        worker.publish('contribution-A-stroke-risk-factor')

        emergency = worker.agent_context(
            'emergency-action.md', ['sources/emergency-guidance.md'])
        emergency_base = emergency['documents'][0]['content']
        unsafe = emergency_base.replace(
            'If stroke is suspected, contact local emergency services immediately. Do not wait for symptoms to improve.\n',
            'If stroke is suspected, wait 30 minutes to see whether symptoms improve before contacting emergency services.\n')
        ident = 'contribution-D-stroke-wait-30-minutes'
        reason = 'Conflict-demo proposal: replace immediate action with a 30-minute waiting period.'
        path = contributions / f'{ident}.contribution.md'
        path.write_text(contribution_file(
            ident, 'contributor-d', reason, 'emergency-action.md',
            emergency['context'], unsafe, emergency_base), encoding='utf-8')
        worker.scan(path, 'contributor-d')
        view = worker.contribution(ident)
        source_version = emergency['context']['sources'][0]['version']
        worker.discuss(
            ident, reviewer, view['bundle_hash'], view['discussion_version'], 'open',
            'Question: Should a person wait 30 minutes before contacting emergency services for a possible stroke?\n'
            'Claim A: emergency-action.md says to contact emergency services immediately and not wait.\n'
            'Claim B: contribution-D-stroke-wait-30-minutes proposes waiting 30 minutes.\n'
            'Scope: first response to suspected stroke symptoms.\n'
            f'Evidence A: sources/emergency-guidance.md@{source_version} explicitly says to contact emergency services immediately and not wait.\n'
            'Evidence B: no supporting versioned evidence was declared.\n'
            'Alternatives: retain immediate action or provide authoritative replacement guidance.\n'
            'Objections: delaying emergency response may be unsafe.\n'
            'Outcome: no consensus; semantic conflict remains open.\n'
            'Next step: reject the conflicting proposal or require authoritative evidence and a new contribution.')
    finally:
        worker.db.close()


def ensure_slack_topics(wiki, state, reviewer, slack):
    """Create one shared concurrent thread and one semantic-conflict thread."""
    worker = Worker(state, LocalFolderStorage(wiki), reviewer, 'Stroke demo owner', slack=slack)
    try:
        shared = worker.discussion_topics(document_path='stroke-basics.md', section_anchor='file')
        if not shared:
            worker.open_concurrent_discussion(
                'contribution-B-stroke-fast-detail', reviewer, 'file',
                'Review whether the published risk-factor change and the pending FAST and prevention changes can coexist. Mention the bot with approve <reason> or reject <reason>.',
                ['contribution-A-stroke-risk-factor',
                 'contribution-C-stroke-prevention-habits'])
        semantic = worker.discussion_topics(
            document_path='emergency-action.md', section_anchor='semantic-conflict')
        if not semantic:
            worker.create_topic(
                'wiki', 'emergency-action.md', 'semantic-conflict',
                'stroke-semantic-conflict', reviewer,
                'Review contribution-D-stroke-wait-30-minutes. Frozen evidence says to contact emergency services immediately and not wait. Mention the bot with approve <reason> or reject <reason>.',
                proposal_id='contribution-D-stroke-wait-30-minutes',
                discussion_id='stroke-semantic-conflict')
        return worker.discussion_topics()
    finally:
        worker.db.close()


def sync_slack_once(wiki, state, reviewer, slack):
    """Poll mapped Slack threads and project unseen human replies into worker state."""
    worker = Worker(state, LocalFolderStorage(wiki), reviewer, 'Stroke demo owner', slack=slack)
    processed = 0
    try:
        for topic in worker.discussion_topics():
            if not topic.get('slack_thread_ts'):
                continue
            thread = {'channel': topic['slack_channel'],
                      'thread_ts': topic['slack_thread_ts']}
            for message in slack.messages(thread):
                if message.get('ts') == topic['slack_thread_ts'] or message.get('bot_id'):
                    continue
                text = (message.get('text') or '').strip()
                if not text:
                    continue
                event_type = ('app_mention' if re.match(
                    r'^\s*<@[A-Z0-9]+>\s*(?:(?:decision|quyết\s+định)\s+)?(?:approve|reject)\b',
                    text, re.I) else 'message')
                result = worker.handle_slack_event({**message, 'type': event_type}, reviewer)
                if not result.get('ignored') and not result.get('duplicate'):
                    processed += 1
        return processed
    finally:
        worker.db.close()


def slack_poll_loop(wiki, state, reviewer, slack, interval):
    while True:
        try:
            processed = sync_slack_once(wiki, state, reviewer, slack)
            if processed:
                print(f'Slack poller projected {processed} new message(s).', flush=True)
        except (SlackError, OSError, ValueError) as exc:
            print(f'Slack poller warning: {exc}', flush=True)
        time.sleep(interval)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--wiki', default='wiki-demo-stroke')
    parser.add_argument('--state', default='.wiki-worker/stroke-demo')
    parser.add_argument('--reviewer', default='reviewer-agent')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8093)
    parser.add_argument('--initialize-only', action='store_true')
    parser.add_argument('--slack-token', default=os.getenv('SLACK_BOT_TOKEN'))
    parser.add_argument('--slack-channel', default=os.getenv('SLACK_CHANNEL'))
    parser.add_argument('--slack-poll', type=int, default=0,
                        help='poll mapped Slack threads every N seconds')
    args = parser.parse_args()
    state_db = Path(args.state) / 'state.sqlite'
    if not state_db.exists():
        if not Path(args.wiki).exists():
            write_seed_wiki(args.wiki)
        initialize(args.wiki, args.state, args.reviewer)
    if args.initialize_only:
        return
    slack = None
    if args.slack_token or args.slack_channel:
        if not args.slack_token or not args.slack_channel:
            parser.error('Slack token and channel must be configured together')
        slack = SlackDiscussion(args.slack_token, args.slack_channel)
        topics = ensure_slack_topics(args.wiki, args.state, args.reviewer, slack)
        for topic in topics:
            if topic.get('slack_thread_ts'):
                print(f'Slack topic {topic["discussion_id"]}: {topic["slack_thread_ts"]}')
    if slack and args.slack_poll > 0:
        threading.Thread(target=slack_poll_loop,
                         args=(args.wiki, args.state, args.reviewer, slack,
                               max(5, args.slack_poll)), daemon=True).start()
    serve(args.host, args.port, args.state, args.wiki, None, args.reviewer,
          'Stroke demo owner', slack)


if __name__ == '__main__':
    main()
