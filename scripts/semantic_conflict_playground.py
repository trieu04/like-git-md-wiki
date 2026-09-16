"""Run a disposable web playground with semantic-conflict examples."""
import argparse
import tempfile
from pathlib import Path

from wiki_worker.core import Worker
from wiki_worker.local import LocalFolderStorage
from wiki_worker.web import serve


def seed(root, reviewer):
    wiki = root / 'wiki'
    wiki.mkdir()
    (wiki / 'policy.md').write_text(
        '# Data storage policy\n\nPrimary records are stored in PostgreSQL.\n', encoding='utf-8')
    (wiki / 'architecture-decision.md').write_text(
        '# Architecture decision\n\nRedis may be used for ephemeral cache. '
        'Primary records must remain in PostgreSQL. Effective: 2026-09-01.\n', encoding='utf-8')
    (wiki / 'legacy-guide.md').write_text(
        '# Legacy guide\n\nUse Redis to improve read performance. '
        'This guide does not define a system of record.\n', encoding='utf-8')

    worker = Worker(root / 'state', LocalFolderStorage(wiki), reviewer, 'Demo owner')
    try:
        context = worker.agent_context(
            'policy.md', ['architecture-decision.md', 'legacy-guide.md'])['context']
        worker.agent_propose({
            'id': 'redis-disputed', 'target': 'policy.md', 'submitter': 'author-agent',
            'reason': 'Claim A says Redis should store all data; Claim B limits Redis to cache.',
            'content': '# Data storage policy\n\nRedis must be used for all persistence.\n',
            'sources': [], 'context': context,
        })
        worker.agent_propose({
            'id': 'redis-scoped', 'target': 'policy.md', 'submitter': 'author-agent',
            'reason': 'Separate cache from the system of record using the architecture decision.',
            'content': ('# Data storage policy\n\nRedis may be used for ephemeral cache. '
                        'Primary records must remain in PostgreSQL.\n'),
            'sources': [], 'context': context,
        })
        worker.agent_propose({
            'id': 'redis-discussion', 'target': 'policy.md', 'submitter': 'author-agent',
            'reason': 'A clean proposal for trying the multi-party Discussion API.',
            'content': ('# Data storage policy\n\nRedis may be used for ephemeral cache. '
                        'Primary records must remain in PostgreSQL.\n'),
            'sources': [], 'context': context,
        })
        for ident in ('redis-disputed', 'redis-scoped'):
            view = worker.contribution(ident)
            worker.discuss(
                ident, reviewer, view['bundle_hash'], view['discussion_version'], 'open',
                'Question: May Redis hold primary records?\n'
                'Claim A: Redis should be used for all persistence.\n'
                'Claim B: Redis is limited to ephemeral cache.\n'
                f'Evidence: architecture-decision.md@{context["sources"][0]["version"]}; '
                f'legacy-guide.md@{context["sources"][1]["version"]}.')
        view = worker.contribution('redis-scoped')
        worker.discuss(
            'redis-scoped', reviewer, view['bundle_hash'], view['discussion_version'], 'comment',
            'The legacy guide discusses read performance and does not designate Redis as the system of record.')
        view = worker.contribution('redis-scoped')
        worker.discuss(
            'redis-scoped', reviewer, view['bundle_hash'], view['discussion_version'], 'resolve',
            'The two source passages apply to different scopes. The proposal states both conditions explicitly.',
            'scoped', ['redis-disputed'])
    finally:
        worker.db.close()
    return wiki


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8080)
    parser.add_argument('--reviewer', default='reviewer-agent')
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='wiki-semantic-playground-') as folder:
        root = Path(folder)
        wiki = seed(root, args.reviewer)
        print('Semantic conflict demo: redis-disputed has an open hold; redis-scoped is resolved.')
        print(f'Open http://{args.host}:{args.port}/ and select redis-discussion to try the Discussion API.')
        print('The playground is disposable and does not modify wiki-en.')
        serve(args.host, args.port, root / 'state', wiki, None, args.reviewer, 'Demo owner')


if __name__ == '__main__':
    main()
