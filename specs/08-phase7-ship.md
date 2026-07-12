# Spec: Phase 7 — Ship (Deploy, Demo, Document)

**Status:** Draft — awaiting review
**Owner:** FlowForge Code Owners
**Depends on:** 07-phase6-dashboard.md (approved + built)
**Gate to exit:** MVP declared complete

## What this phase delivers

The project becomes presentable: deployed once to AWS for a recorded demo, torn down, and documented so the repo alone tells the whole story (architecture, eval results, run instructions). "Deployed" for a portfolio piece means demonstrably deployable — not always-on.

## Scope (in)

### 1. Production build & compose
- Production Dockerfiles (multi-stage: build → slim runtime) for backend and frontend (frontend served as static build behind the backend or a tiny nginx).
- `docker-compose.prod.yml`: backend, frontend, db, redis, worker as distinct services; healthchecks; restart policies; volumes for Postgres data + uploads.
- Config strictness: prod refuses to start with missing required env vars, debug endpoints disabled (`APP_ENV=prod` kills the dev-only retrieve endpoint), CORS locked to the deployed origin.
- LLM in prod-demo: decide at plan review — OpenAI (small budget, better output for the recording) with cost cap, or Ollama on the instance (needs a larger instance). Default proposal: OpenAI for the recorded demo, spend ≤ $10.

### 2. AWS deployment (single EC2 + Compose — deliberate simplicity, D11)
- One EC2 instance (free-tier eligible size if it fits; else smallest that runs the stack), security group: 80/443 + SSH from own IP only.
- Deploy script or documented runbook: provision → install Docker → pull repo → env file → compose up → seed script → smoke test.
- HTTPS: Caddy or nginx + Let's Encrypt if a domain is used; plain HTTP on IP acceptable for a recorded demo (state the tradeoff in README).
- Auth0 callback URLs updated for the deployed origin.
- **Teardown runbook:** stop instance, snapshot optional, terminate, remove Auth0 URLs — with a checklist so nothing keeps billing.

### 3. The recorded demo
- Script the MVP definition-of-done steps 1–10 as a shot list (login as admin → upload policy PDF → indexed → login as operator → VPN ticket → triage → evidence/citations → pause → login as approver → approve → execution + confirmation → dashboard + audit).
- Use distinct users per role in the recording (segregation of duties visible).
- 5–8 minutes, voiceover or captions. Stored in the repo README (link) — not just on a drive.

### 4. Documentation (the repo as portfolio artifact)
- README final form: what it is (3 sentences), architecture diagram (from ARCHITECTURE.md), demo video link, quickstart (local compose up in ≤5 commands), eval results table (agent_version comparison from Phase 5), tech decisions link (DECISIONS.md), known limitations & future work (Jira adapter, RLS, reranking, notifications, OCR — collected from every spec's out-of-scope lists).
- Interview crib sheet `docs/talking-points.md`: the durable pause, segregation of duties, grounding-in-code, judge≠triage model, cost-conscious design — each as a 3-sentence story.

## Scope (out)
- ECS/EKS/Kubernetes, CI/CD pipelines to AWS, autoscaling, managed RDS (all named as "production path" in README).
- Always-on hosting; custom domain (optional).

## Gates & checks
- **G7.1 Cold-start:** on a fresh clone, `README` quickstart alone brings the stack up locally and passes the health check (tested by actually doing it).
- **G7.2 Prod config:** prod compose refuses to boot with a missing secret; debug endpoints 404 in prod mode.
- **G7.3 Deployed smoke:** on the EC2 deployment, the full MVP journey (steps 1–10) completes once, live.
- **G7.4 The recording:** demo video captures the full journey with distinct role logins; committed/linked in README.
- **G7.5 Teardown:** checklist executed; AWS bill shows no lingering resources after 24h.
- **G7.6 Repo review:** a cold reader (or a fresh Claude session given only the repo) can explain the system and run it — the ultimate documentation test.

## Definition of done
- G7.1–G7.6 all pass. Demo recorded and linked. AWS torn down. README final.
- MVP definition-of-done demonstrated live on the deployment and captured on video.
- The repo, standing alone, is the portfolio piece.

## Risks
- Free-tier instance too small for the stack. Mitigation: worker + Ollama are the heavy parts; using OpenAI for the demo removes Ollama from the instance.
- Deployment yak-shaving eating days. Mitigation: single-EC2-plus-compose is a hard constraint; anything fancier is explicitly post-MVP.

## Task plan
*(Filled after spec approval — review gate.)*
