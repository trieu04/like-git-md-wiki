"""Continuously dispatch a real Codex reviewer for new Slack decision requests."""
import argparse
import json
import os
import sqlite3
import subprocess
import time
from pathlib import Path
from urllib.request import urlopen

from wiki_worker.slack import SlackDiscussion


def read_json(url):
    with urlopen(url, timeout=10) as response:
        return json.load(response)


def load_ledger(path):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (FileNotFoundError, ValueError):
        return {'processed': {}}


def save_ledger(path, ledger):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(ledger, indent=2, ensure_ascii=False), encoding='utf-8')
    temporary.replace(path)


def topic_for(state, proposal_id):
    db = sqlite3.connect(Path(state) / 'state.sqlite')
    db.row_factory = sqlite3.Row
    try:
        row = db.execute(
            '''SELECT discussion_id,slack_channel,slack_thread_ts
               FROM discussion_topics WHERE proposal_id=? AND slack_thread_ts IS NOT NULL
               ORDER BY created_at LIMIT 1''', (proposal_id,)).fetchone()
        return dict(row) if row else None
    finally:
        db.close()


def reviewer_prompt(base_url, proposal_id, request):
    return f'''Act as the configured wiki reviewer `reviewer-agent` for one demo request.

Work in the current repository. Read AGENTS.md, skills/wiki-knowledge-workflow/SKILL.md and all reviewer/conflict references it requires. Do not edit source files.

Read {base_url}/api/contribution/{proposal_id} and inspect the exact artifact, frozen base, current content, source snapshots, freshness, diffs, semantic/workflow discussion versions, and reviewer_decision_requests.

The triggering Slack request is:
- request_id: {request['request_id']}
- actor: {request['actor']}
- decision requested: {request['decision']}
- reason: {request['reason']}

Preserve that actor and reason in your rationale, but decide independently under the project review rules. If approval is blocked by stale context, insufficient evidence, or an open hold, submit an explicit rejection with a concrete revision request. Otherwise apply the supported approve/reject decision through POST /api/contribution/{proposal_id}/review using actor `reviewer-agent` and every exact current field required by the API. Do not publish. End with a concise result including final contribution state and rationale.'''


def run_agent(root, base_url, proposal_id, request, output_file):
    command = ['codex', 'exec', '--ephemeral', '-C', str(root),
               '-s', 'danger-full-access', '-a', 'never',
               '-o', str(output_file), '-']
    result = subprocess.run(command, input=reviewer_prompt(base_url, proposal_id, request),
                            text=True, timeout=900)
    summary = output_file.read_text(encoding='utf-8').strip() if output_file.exists() else ''
    return result.returncode, summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='http://127.0.0.1:8093')
    parser.add_argument('--state', default='.wiki-worker/stroke-demo')
    parser.add_argument('--interval', type=int, default=10)
    parser.add_argument('--once', action='store_true')
    parser.add_argument('--slack-token', default=os.getenv('SLACK_BOT_TOKEN'))
    args = parser.parse_args()
    root = Path.cwd().resolve()
    state = Path(args.state)
    ledger_path = state / 'agent-loop.json'
    output_file = state / 'agent-last-result.txt'
    slack = SlackDiscussion(args.slack_token, '') if args.slack_token else None

    print('Stroke reviewer agent loop is running.', flush=True)
    while True:
        ledger = load_ledger(ledger_path)
        try:
            queue = read_json(args.base_url + '/api/contribution')
            for item in queue:
                if item['state'] != 'pending':
                    continue
                for request in item.get('reviewer_decision_requests', []):
                    if request['request_id'] in ledger['processed']:
                        continue
                    print(f'Dispatching reviewer for {item["id"]} / {request["request_id"]}',
                          flush=True)
                    code, summary = run_agent(root, args.base_url, item['id'], request,
                                              output_file)
                    final = read_json(args.base_url + '/api/contribution/' + item['id'])
                    ledger['processed'][request['request_id']] = {
                        'proposal_id': item['id'], 'exit_code': code,
                        'final_state': final['state'], 'processed_at': time.time()}
                    save_ledger(ledger_path, ledger)
                    topic = topic_for(state, item['id'])
                    if slack and topic:
                        slack.channel = topic['slack_channel']
                        slack.post({'channel': topic['slack_channel'],
                                    'thread_ts': topic['slack_thread_ts']},
                                   'Reviewer agent completed request '
                                   f'`{request["request_id"]}`. State: *{final["state"]}*\n'
                                   + (summary[:2500] or f'Codex exited with code {code}.'))
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            print(f'Agent loop warning: {exc}', flush=True)
        if args.once:
            return
        time.sleep(max(5, args.interval))


if __name__ == '__main__':
    main()
