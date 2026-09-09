# Long-term knowledge model — reference

This design predates the scope reduction. It is not the Phase 1 specification. The [README](../README.md), [design](design.md), and [implementation plan](implementation-plan.md) take precedence. Sections called “foundation phase” below record an earlier proposal; a claim graph, event sourcing, policy engine, and bitemporal queries are not implementation commitments.

## Goal

Many people and AI agents contribute to a graph knowledge base, expressed as linked Markdown documents on Microsoft 365 SharePoint. This phase prepares structure, context, and accountability for future contradiction detection, source assessment, domain arbitration, relation assessment, and knowledge cleanup.

This is a foundation design for discussion, not an implemented system. Git suggests ways to retain snapshots and propose changes; it supplies no model of truth, authority, or knowledge validity. SharePoint provides collaboration and storage.

**The managed units are statements and relations with provenance, proposed and decided within specific contexts.** Files are presentation and transport units. One file can contain multiple claims; one claim may appear in multiple files.

## Invariants

1. Stable identity differs from content version. Renaming a document preserves its ID; changing a claim's meaning creates a revision or a new claim with explicit lineage.
2. Ingesting a contribution does not accept its claims. An agent assessment does not automatically become an authoritative decision.
3. Claims, sources, relations, assessments, and decisions are separate objects.
4. History is immutable by default; current state derives from events and decisions. Mandatory deletion under data policy is an audited exception; deleted content is not promised to remain reproducible.
5. Unknown values are allowed. Do not infer valid times, original authors, domain owners, or reliability automatically.
6. Each assessment binds to specific input versions, methods, and scope. Do not carry old assessments into new revisions automatically.
7. Contradictory claims may coexist in storage. Policy-based views determine what appears as currently applicable knowledge.

## Conceptual model

| Object | Role and core data |
| --- | --- |
| Document / Revision | Stable ID, blob hash, current path, anchors, and claim mappings |
| Claim / Revision | Verbatim statement, language, scope, applicability conditions, domain, and declared valid time; optional subject/predicate/object structure |
| Source / Revision | Origin, issuing person/organization if known, URI, retrieval time, retained copy or fingerprint, access restrictions |
| EvidenceBinding | Claim revision → source revision, quotation/locator, and declared role: support, rebuttal, or context |
| Relation / Revision | Own ID, type, direction, endpoints, scope, provenance; claim endpoints must specify revisions |
| Contribution / Revision | Intent, delta, base snapshot, read/write sets, submitter, agent run, and reason |
| Assessment | Target revisions, evaluator, method/version, inputs, findings, evidence, time, and limitations |
| Decision | Target revisions, action, decision-maker, domain/scope, reason, policy revision, and validity |
| AuthorityPolicy | Domain, roles, decision rights, delegation, escalation, and valid time |
| Event / Snapshot | Recorded history; snapshots pin content, graph, decisions, and policy at a point in time |

A graph database is not immediately necessary. Records with IDs and explicit relations can live in JSON; indexes are rebuildable projections. Stable IDs identify objects; hashes identify revision content. Identical claim text may still have different scope and origins, so text hashes must not automatically unify claims.

## Markdown and the graph

Markdown remains the human reading and authoring format; sidecar metadata stores IDs, mappings, and structured relations.

- A Markdown link initially means only `links_to`, not `supports`, `causes`, or `contradicts`.
- Claim mappings reference document revisions and anchors or hashed quotations. Line numbers are for display only; unresolved anchors require mapping review.
- A new document revision does not update old claims automatically. Agents or contributors propose new mappings; unanalyzed content remains `unmapped`.
- Claim extraction is a proposal with provenance. Importing an old wiki does not make every sentence an accepted claim.
- Change Markdown and sidecars in the same contribution; validators detect mappings to incorrect revisions.

Do not immediately force knowledge into triples. Preserve exact wording, qualifiers, and source passages to retain meaning; structure can be added later.

## Provenance and time

Distinguish the authenticated submitter, requester/delegator if any, executing agent, original speaker in the source, and decision-maker. Do not combine them into one `author` field; requesting agent work does not automatically endorse its output.

AgentRun records agent identity, configuration/tool/model versions when available, input revisions, retrieved sources, and output hashes. Retain instructions according to data policy, without requiring internal reasoning. Metadata supports tracing but does not guarantee exact reproduction of model output.

Two independent time axes:

- **Valid time:** when a statement or decision applies within its domain.
- **Recorded time:** when the system records information, using service-side time.

Source publication and retrieval dates are separate metadata. Unknown validity differs from an unbounded interval. Retroactive corrections must retain what the system previously knew. Queries must distinguish “according to what was known on date X” from “applicable on date Y.”

If permissions or copyright prevent retaining a source, record a locator/fingerprint and reproducibility limits. Sources quoted indirectly by agents should preserve the derivation chain when known; multiple agents repeating one source are not independent evidence.

## Contributions, assessments, and decisions

```text
Person / agent -> Contribution + context snapshot
                         |
                Structure and permission checks
                         |
                Record candidate objects
                         |
                Assessment with evidence
                         |
                Decision under authority policy
                         |
                View by domain and time -> Markdown wiki
```

Contribution lifecycle (`submitted`, `validated`, `integrated`, `rejected`) is independent of assessment lifecycle (`pending`, `completed`, `outdated`) and claim disposition. Recorded claims may still lack assessments or decisions.

Disposition is calculated by domain/scope/time/policy: undecided, accepted, disputed, or retracted. Do not use one global `approved` boolean. `archived` is a presentation/storage state, not a statement that the claim is false.

AuthorityPolicy has revisions. Each decision references the policy effective at decision time, verified authority, and permitted scope. Policy changes do not rewrite history but may require another review. Overlapping domains or missing owners await arbitration; do not automatically select a final decision-maker. Agents propose and assess by default, and decide only with explicit policy delegation.

## Preparing for future capabilities

| Capability | Foundation to retain now | Not automated |
| --- | --- | --- |
| Semantic conflict detection | Claim revisions, scope/qualifiers, valid time, sources, snapshots; issues referencing multiple claims | Adjudicating and resolving contradictions |
| Provenance & temporal validity | Versioned source passages, actor chain, two time axes, provenance completeness | Inferring source reliability or continued claim correctness |
| Authority & accountability | Versioned domains/policies; decisions with accountable actors, rationale, and scope | Choosing owners or granting authority |
| Graph quality / edge evaluation | Typed, directed, versioned relations; assessments with criteria and evaluators | A universal truth score or automatic edge-direction correction |
| Denoising lifecycle | Lineage, dependency index, reasoned merge/supersede/archive/retract actions | Automatic deletion/merging based on similar text |

Relation scores must identify what they measure: evidence support, relevance, freshness, or detector confidence. Retain scales and method versions; do not combine different scores without calibration. A versioned relation-type registry must define direction and symmetry; edge direction is not a confidence score.

Detectors create assessments/issues with claim revisions, overlapping scope, evidence, and explanations. An issue can be dismissed by a reasoned decision; it does not directly delete claims or turn a contradiction relation into confirmed truth.

## Denoising and downstream impact

`merge` creates a destination object and retains mappings from old IDs; `supersede` specifies the scope/time of replacement; `archive` removes an object from default views; `retract` records withdrawal. Supersession does not automatically imply that the earlier claim was never correct.

Each action requires a proposal and appropriately authorized decision. Do not silently transfer evidence, edges, or approvals to new objects. A dependency index answers “if this claim changes, which assessments, relations, decisions, and documents are affected?” Dependents become `needs_review`, not automatically false.

For example, “retain logs for 30 days” before July 1 and “retain logs for 90 days” from July 1 differ without contradicting each other if their valid periods do not overlap. If both apply in August, domain and conditions still need inspection before concluding a contradiction. The domain owner's decision must preserve evidence and history for both claims.

## Snapshots and concurrent collaboration

A snapshot pins the document tree, graph records, evidence references, policy revisions, and an event-ledger position. Manifests may reference trees by hash; a complete Merkle DAG is not necessary yet. Retain blobs so content remains retrievable.

Contributions declare `base_snapshot`, a `read_set` with exact revisions, a `write_set` with expected revisions, and external sources. The read set declares the context used; it does not prove that an agent understood everything.

Two independent proposals can both be recorded. Applying a delta checks revisions of modified objects; decisions additionally check declared policy, evidence, and dependencies. Changed inputs produce `needs_revalidation`, not a semantic conflict. Do not make every contribution stale because an unrelated document changed.

Read sets do not detect newly appearing claims or unknown semantic relations. Absence of write conflicts does not guarantee absence of knowledge contradictions. Assessments must retain the graph/domain snapshot to establish their assessment scope.

An initial implementation may use one coordinator to serialize recording and decisions while agents read, propose, and assess concurrently. Events have idempotency keys and coordinator-assigned order; projections have checkpoints and are rebuildable. Do not use file-sync order or personal computer timestamps as decision order.

## SharePoint and storage boundaries

```text
wiki/                 Markdown for readers
contributions/        Proposal bundles; suffix signals readiness for ingestion
knowledge/
  objects/            Immutable content/revisions, graph records, evidence
  snapshots/          Manifests pinning revisions and history positions
  events/             Contribution, assessment, decision, lifecycle events
  policies/           Authority policy revisions
  views/              Rebuildable projections/indexes and checkpoints
```

This is a logical structure, not a finalized physical schema. Cron only ingests, validates, and coordinates; `.ready` does not mean claims are approved. One publisher produces Markdown views; multiple evaluators may add assessments.

Authoritative records must be separate from projections. Write permissions protect history; hashes do not stop someone authorized to edit both content and hashes. Graphs/indexes/views must not expose data beyond source permissions. Snapshots follow company retention/deletion policies and access revocation.

Transport details and multi-file publication limits are retained in the [SharePoint draft](sharepoint-transport-draft.md). Verify Microsoft Graph behavior before implementation. Logical snapshots do not imply atomic updates to multiple files displayed on SharePoint.

## Foundation phase scope

1. IDs/revisions, schema versions, canonical hashing, and retrievable snapshots.
2. Documents, claims, relations, sources/evidence, and mappings, allowing unstructured portions.
3. Contributions, actor/agent provenance, read/write sets, and concurrency checks.
4. Separate Assessment/Decision objects; minimum authority policy and service-side permission checks.
5. Event ledger, projections, temporal queries, and dependency invalidation.
6. Manual lifecycle events; no automatic arbitration or denoising algorithms yet.

Future evaluator contract: accept snapshots and target revisions; return assessments with inputs, method/version, findings, evidence, and limitations. Evaluators do not directly edit claims or official views. Semantic detectors and edge scorers can be added without changing the accountability/history model.

No graph database, agent framework, semantic comparison algorithm, universal quality score, or complete domain ontology has been chosen. These choices require real data.

## Design validation scenarios

- Renaming preserves IDs, mappings, and source history.
- Two agents citing one source do not count as two independent pieces of evidence.
- Claims with identical text but different scope/time are not automatically merged.
- Ingestion does not accept claims; high confidence does not override authority.
- Changed sources or revisions require review of related assessments; old results remain retrievable.
- Retroactive decisions correctly answer both “what was known then” and “what is now considered applicable then.”
- Merge/supersede retain lineage without automatically transferring approval/evidence.
- Retries do not duplicate events; rebuilding a projection for the same snapshot/policy/query time gives the same result.
- Actors without domain authority cannot decide by editing a manifest.
- Restricted or mandatorily deleted sources do not leak through indexes; reproducibility limits are explicit.

The next step is to test the model against real company knowledge scenarios before finalizing schema v1, especially claim boundaries, overlapping domains, valid times, and decision rights for each action.
