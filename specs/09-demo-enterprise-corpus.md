# Spec: Demo Enterprise & Knowledge Corpus

**Status:** Approved (2026-07-12, FlowForge Code Owners)
**Owner:** FlowForge Code Owners
**Depends on:** 00-mvp-definition.md
**Feeds:** 02-phase1-rag.md (fixture docs + eval seed set), 03-phase2-triage-agent.md (label space), 06-phase5-eval-observability.md (scoring)

## Why this spec exists

The MVP's quality ceiling is its knowledge corpus. The agent can only be as good as the documentation it retrieves from, the eval numbers only mean something if ticket labels are genuinely justifiable from the docs, and the demo only lands if the fictional company feels real. Instead of "3 loose fixture docs," we build one coherent fictional enterprise — with named teams, a closed routing taxonomy, and a documentation set written to a reusable template — so that (a) retrieval, grounding, and eval all share one consistent world, and (b) the template becomes the onboarding pattern for any future company.

## The fictional enterprise

**Meridian Dynamics, Inc.** — a fictional mid-size logistics-software company, ~900 employees, offices in two cities plus remote staff. Explicitly fictional; no real-company names, branding, or data anywhere in the corpus.

### Support teams (the closed `recommended_team` label space)

| Team | Handles |
|---|---|
| Service Desk | tier-1 catch-all, general inquiries, triage fallback |
| IT Infrastructure | network, VPN, Wi-Fi, servers, DNS |
| IT Security | account access control, MFA, phishing, security incidents |
| Workplace IT | laptops, peripherals, printers, meeting rooms |
| Business Applications | email/collaboration tools, ERP, SaaS licensing |

### Closed taxonomies (the agent's structured-output label space)

- `category`: `network_access` | `account_access` | `hardware` | `software_licensing` | `email_collaboration` | `security_incident` | `general_inquiry`
- `urgency`: `low` | `medium` | `high` | `critical`
- `priority`: `P1`–`P4`, defined by the priority matrix in MD-IT-002 (impact × urgency)

These enums are the single source of truth for the Phase 2 Pydantic output schema and the Phase 5 eval scoring. They live in one fixture file (`fixtures/enterprise/taxonomy.json`) that both the corpus and the code import — no drift.

## The document template (the reusable onboarding schema)

Every corpus document follows `fixtures/enterprise/TEMPLATE.md`:

**Front matter (metadata block):**
- Doc ID (`MD-IT-NNN`), Title, Version, Effective date, Owner team, Applies to, Review cadence

**Numbered body sections (fixed order; omit N/A sections rather than leaving them empty):**
1. Purpose — one paragraph, what this document governs
2. Scope — who/what it applies to, explicit exclusions
3. Definitions — terms used, matching ticket vocabulary
4. Policy / Procedure — the actual rules or steps, numbered
5. Priority & escalation — which team owns this, target response, when to escalate (explicit team names from the table above)
6. Related documents — doc IDs
7. Revision history

**Authoring rules (what makes the corpus RAG-ready — these are requirements, not suggestions):**
- One topic per section; each section self-contained and understandable without the rest of the doc (chunk-friendly, ~150–400 words per section).
- Every routable fact stated explicitly in prose: team names, priority levels, SLAs, escalation triggers. Nothing lives only in a table, image, or header.
- Terminology matches how employees actually write tickets ("VPN keeps disconnecting", "locked out of my account") — include common phrasings in Definitions or the procedure text so retrieval bridges vocabulary gaps.
- Concrete thresholds, not vibes: "outage affecting ≥ 10 users is P1", not "major outages are high priority".
- Cross-references by Doc ID so citations stay resolvable.
- No real product names where avoidable; fictional internal system names (e.g. "MeridianConnect VPN") used consistently corpus-wide.

The template plus an `AUTHORING.md` guide is itself a deliverable — it is the pattern for onboarding the next company.

## The corpus (10 documents, all three ingestion formats)

| ID | Title | Format |
|---|---|---|
| MD-IT-001 | VPN Access Policy | PDF |
| MD-IT-002 | Incident Priority & Escalation Guidelines (the P1–P4 matrix) | PDF |
| MD-IT-003 | Password Reset & Account Lockout Procedure | MD |
| MD-IT-004 | MFA Enrollment & Recovery | MD |
| MD-IT-005 | Hardware Request & Replacement Policy | MD |
| MD-IT-006 | Software & SaaS License Request Procedure | MD |
| MD-IT-007 | Email & Collaboration Troubleshooting Guide | MD |
| MD-IT-008 | Security Incident Reporting Policy | PDF |
| MD-IT-009 | Onboarding & Offboarding IT Checklist | TXT |
| MD-IT-010 | Remote Work IT Standards | MD |

- PDFs are generated from Markdown sources (sources committed too) so they are clean text-layer PDFs with real page numbers — exercising the Phase 1 page-metadata requirement without OCR.
- MD-IT-001 is the document the MVP definition-of-done demo uploads live (step 2: "Admin uploads an IT policy PDF"; step 4: VPN ticket).
- Corpus deliberately covers every category in the taxonomy so no eval label is ungroundable.

## The ticket set

`fixtures/eval_tickets.json` — **20 labeled eval tickets** + **5 unlabeled demo tickets** (for live-demo variety). Each eval ticket has:

- Input fields: title, description, requester department, affected service, optional existing priority (matching the New Ticket form exactly).
- Labels: expected `category`, `urgency`, `recommended_team`.
- **Grounding reference: the doc ID + section number that justifies each label.** This is what makes gate G1.5 (label review) checkable and lets `fixtures/retrieval_checks.json` be derived instead of hand-invented.

Difficulty mix (deliberate, documented per ticket):
- ~12 straightforward — one category, clearly covered by one doc.
- ~5 ambiguous — multi-topic (e.g. "can't reach the ERP over VPN"), or vocabulary mismatch with the docs; tests real retrieval, not string matching.
- ~3 adversarial — out-of-corpus topic (correct behavior: low confidence, `general_inquiry`, Service Desk), vague description, or conflicting signals (user says "urgent" but matrix says P4).

## Who builds it

Per the Codex integration spec (10): **Codex drafts** the corpus documents, tickets, and taxonomy files from this spec (development-time fixture generation is its lane); **the FlowForge Code Owners review** every document and every label before merge — G1.5 stays a human gate. Everything lands under `fixtures/enterprise/` and `fixtures/`, never under `backend/app/`.

## When it's built

Phase 1, alongside the ingestion pipeline (the Phase 1 spec's "Eval seed set" section is superseded by this spec — its numbers move from "≥3 docs / 15–20 tickets" to this corpus). Taxonomy file lands first since the Phase 2 output schema depends on it.

## Gates & checks

- **G9.1 Template compliance:** every corpus doc passes a structural check against the template (front-matter fields present, numbered sections in order) — scripted, in `scripts/`.
- **G9.2 Label traceability:** every eval label's grounding reference points at a real doc section, and a code owner has reviewed each (absorbs G1.5).
- **G9.3 Taxonomy closure:** every ticket label ∈ taxonomy.json; every taxonomy category is exercised by ≥1 ticket and grounded by ≥1 doc.
- **G9.4 Format coverage:** corpus includes ≥2 PDFs, ≥1 TXT, rest MD — all three ingestion paths exercised by real fixtures.

## Out of scope

- Multi-language documents; scanned/OCR PDFs; real company data of any kind.
- More than one fictional company for the MVP (the template is the multi-company story; a second corpus is future work).
- HR/legal/finance policy domains — IT support only.

## Task plan
*(Filled after spec approval — review gate.)*
