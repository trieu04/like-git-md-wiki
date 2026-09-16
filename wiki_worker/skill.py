"""Build standalone, downloadable skills for external agents."""
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent / 'skills' / 'wiki-knowledge-workflow'

ROLES = {
    'contributor': {
        'name': 'wiki-contributor',
        'filename': 'wiki-contributor-skill.md',
        'description': 'Create a versioned Markdown contribution for the wiki reviewer workflow.',
        'source': SKILL_ROOT / 'references' / 'contribution.md',
    },
    'reviewer': {
        'name': 'wiki-reviewer',
        'filename': 'wiki-reviewer-skill.md',
        'description': 'Review and optionally publish pending wiki contributions using the reviewer API.',
        'source': SKILL_ROOT / 'references' / 'reviewer.md',
    },
}


def skill_file(role):
    item = ROLES[role]
    body = item['source'].read_text(encoding='utf-8')
    references = ['merge-conflicts']
    if role == 'reviewer':
        references.append('semantic-conflicts')
    for reference in references:
        extra = (SKILL_ROOT / 'references' / f'{reference}.md').read_text(encoding='utf-8')
        anchor = {'merge-conflicts': 'merge-and-conflict-logic',
                  'semantic-conflicts': 'semantic-content-disputes'}[reference]
        body = body.replace(f']({reference}.md)', f'](#{anchor})')
        body += '\n\n' + extra
    header = f"---\nname: {item['name']}\ndescription: {item['description']}\n---\n\n"
    return item['filename'], (header + body).encode('utf-8')


def describe():
    return {role: {'name': item['name'], 'filename': item['filename'],
                   'download': f'/api/skill/{role}'} for role, item in ROLES.items()}
