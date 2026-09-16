# Semantic content disputes

Use this procedure when claims disagree, including claims in separate paragraphs or files. Fresh hashes and a clean text merge do not establish semantic compatibility. The reviewer judges evidence; the worker records deliberation and enforces the hold.

## Frame the disagreement

Quote each claim and locate it in the base, proposal, related file or competing contribution. Compare subject, definition, environment, population, units, effective time and modality (`must`, `should`, `may`). Claims that apply to distinct scopes can coexist; opposite instructions for the same scope cannot merely be placed beside each other.

For each position, name the source path, exact version and supporting passage from captured context. Assess whether the source directly supports the wording, applies to this claim and is effective rather than superseded. Observation version is not an effective date. Expertise helps interpret evidence but is not proof or approval authority.

Distinguish descriptive facts, normative decisions and recommendations. An internal decision can establish a rule when its authority, approval, scope and effective date are documented. Do not manufacture a factual conclusion from sources that do not directly support it.

## Record and resolve

Read `GET /api/contribution/ID`, then append to `POST /api/contribution/ID/discussion` using the exact `bundle_hash` and `discussion_version`. Use this shape for the reason:

```text
Question: [neutral question]
Claim A / Claim B: [wording, passage and contribution IDs]
Scope: [subject, conditions and effective dates]
Evidence A/B: [source path@version and supporting passage]
Alternatives: [choose / narrow scope / attribute / revise]
Objections: [unanswered concerns and responses]
Independent input: [actor and provenance]
Outcome: [resolution or no consensus]
Next step: [specific missing evidence or decision]
```

- `open` starts a hold; `reopen` starts it again after a resolution.
- `comment` adds evidence or records no consensus and leaves the hold open.
- `resolve` requires `supported`, `scoped`, `attributed`, or `not_a_conflict`. It removes the hold from the exact frozen proposal but does not approve, edit or publish it.
- If wording or evidence changes, create a new contribution with fresh context. Link predecessor IDs and the discussion in its Reason. Mentioning a new source in a comment does not freeze it as evidence.
- Rejecting an open dispute is allowed when requesting revision. It does not claim that the semantic question was resolved.

Read the contribution again before review. The review request must include its `discussion_version`; a concurrent discussion event makes the review snapshot invalid. An open hold blocks approval but not an explicit rejection.

## MVP limits

The configured reviewer is the only discussion writer. The UI does not contact experts or provide a multi-user Talk page. Record outside input and its provenance without treating headcount, seniority or confidence as votes.

The hold belongs to one contribution and does not propagate to another ID or an already published page. Corrections after publication require another contribution. Multiple affected files still publish one at a time; a scope table is not an atomic transaction. The worker does not discover contradictions or judge the quality of arguments.
