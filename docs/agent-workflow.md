# Agent workflow

The reusable [Wiki Knowledge Workflow skill](../skills/wiki-knowledge-workflow/SKILL.md) has two roles: [authoring contribution files](../skills/wiki-knowledge-workflow/references/contribution.md) and [reviewing contributions](../skills/wiki-knowledge-workflow/references/reviewer.md).

Authors discover/search files directly, use the context CLI to get versions, and deliver a file or bundle. Reviewers use the UI or the combined `/api/contribution/ID` read/artifact tool. UI forms have named fields and readable outputs, not a JSON runner. Skill documents appear under the Skill sidebar category and are served by `GET /api/skill`.
