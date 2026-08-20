/**
 * Workflow run detail (spec 07 screen 7) — the centerpiece.
 *
 * This is the screen that has to make the grounding rule visible. A
 * recommendation is not grounded unless it carries at least one valid
 * citation, and "valid" means the cited `chunk_id` is actually present in the
 * evidence the model was shown. So the panel does three things:
 *
 *   1. renders every retrieved chunk with its document title, page and section,
 *   2. marks the ones the model cited, distinctly enough to see at a glance,
 *   3. **names any citation that does not resolve** rather than silently
 *      dropping it.
 *
 * Point 3 is what G6.3 asserts. A UI that quietly skips an unresolvable
 * citation would make a broken run look like a clean one — which is precisely
 * the failure the grounding rule exists to catch, hidden by the screen meant
 * to reveal it.
 */

import { Link, useParams } from "react-router-dom";

import { isActive, useRun, useTicket } from "../api/hooks";
import type { EvidenceChunk, RunStatus } from "../api/types";
import {
  Empty,
  ErrorState,
  Loading,
  Maybe,
  Mono,
  PageHead,
  Panel,
  RunBadge,
  ShortId,
  CopyId,
  formatDateTime,
} from "../components/ui";
import { useTitle } from "../shell/Shell";
import { TID, testid } from "../testids";

/** The happy path, in order. `failed` and `rejected` are ends, not steps. */
const STEPS: { key: string; label: string; reached: RunStatus[] }[] = [
  { key: "queued", label: "Queued", reached: ["queued", "running", "awaiting_approval", "executing", "completed", "rejected"] },
  { key: "triage", label: "Triage", reached: ["running", "awaiting_approval", "executing", "completed", "rejected"] },
  { key: "approval", label: "Approval", reached: ["awaiting_approval", "executing", "completed", "rejected"] },
  { key: "execute", label: "Execute", reached: ["executing", "completed"] },
  { key: "done", label: "Complete", reached: ["completed"] },
];

function Timeline({ status }: { status: RunStatus }) {
  const failed = status === "failed";
  const rejected = status === "rejected";
  return (
    <div className="stepper" {...testid(TID.runTimeline)}>
      {STEPS.map((step, index) => {
        const done = step.reached.includes(status);
        const current =
          (status === "queued" && step.key === "queued") ||
          (status === "running" && step.key === "triage") ||
          (status === "awaiting_approval" && step.key === "approval") ||
          (status === "executing" && step.key === "execute") ||
          (status === "completed" && step.key === "done");
        const cls = current
          ? "step step--current"
          : done
            ? "step step--done"
            : "step";
        return (
          <span key={step.key} style={{ display: "contents" }}>
            {index > 0 && <span className="step__rule" />}
            <span className={cls}>
              <span className="step__num">{done && !current ? "✓" : index + 1}</span>
              {step.label}
            </span>
          </span>
        );
      })}
      {(failed || rejected) && (
        <>
          <span className="step__rule" />
          <span className="step step--failed">
            <span className="step__num">!</span>
            {failed ? "Failed" : "Rejected — no write"}
          </span>
        </>
      )}
    </div>
  );
}

function EvidenceItem({ chunk, cited }: { chunk: EvidenceChunk; cited: boolean }) {
  const location = [
    chunk.page !== null && chunk.page !== undefined ? `p.${chunk.page}` : null,
    chunk.section ?? null,
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <div
      className={cited ? "evidence__item evidence__item--cited" : "evidence__item"}
      {...testid(TID.evidenceItem(chunk.chunk_id))}
    >
      <div className="evidence__head">
        <span className="evidence__title">{chunk.document_title ?? "Untitled document"}</span>
        {location && <span className="evidence__loc">{location}</span>}
        {cited && (
          <span className="badge badge--accent" {...testid(TID.evidenceCited(chunk.chunk_id))}>
            cited
          </span>
        )}
        {chunk.score !== null && chunk.score !== undefined && (
          <span className="evidence__score">
            {chunk.score.toFixed(3)}
            <span className="evidence__meter">
              <span style={{ width: `${Math.max(0, Math.min(1, chunk.score)) * 100}%` }} />
            </span>
          </span>
        )}
      </div>
      {chunk.text && <p className="evidence__text">{chunk.text}</p>}
      <div className="evidence__loc" style={{ marginTop: "var(--sp-2)", opacity: 0.7 }}>
        {chunk.chunk_id}
      </div>
    </div>
  );
}

export function RunDetail() {
  const { runId } = useParams<{ runId: string }>();
  useTitle("Run");
  const run = useRun(runId);
  const ticket = useTicket(run.data?.ticket_id);
  // No `/api/audit` call here. That route is administrator-only, but run
  // detail is an any-persona screen and `GET /api/runs/{id}` already returns
  // this run's audit entries, tenant-scoped, to whoever may read the run.
  // Reaching for the global endpoint meant operators and approvers saw no
  // trail at all on a screen the spec says includes one.

  if (run.isPending) return <Loading label="Loading run" />;
  if (run.isError) return <ErrorState error={run.error} onRetry={() => void run.refetch()} />;
  if (!run.data) return <Empty title="Run not found" />;

  const r = run.data;
  const output = r.output ?? {};
  const evidence = r.evidence ?? [];
  const citations = output.citations ?? [];

  const evidenceIds = new Set(evidence.map((c) => c.chunk_id));
  // Only chunks that actually exist in the evidence. Deduplicated, because a
  // model citing the same chunk twice has supported one claim, not two — and
  // reporting "2 citations" beside "1 cited" is the kind of small dishonesty
  // that makes a reader distrust every other number on the page.
  const citedIds = new Set(citations.map((c) => c.chunk_id).filter((id) => evidenceIds.has(id)));
  // The grounding rule, evaluated in the open: a citation naming a chunk that
  // was never retrieved is not evidence of anything.
  const unresolved = citations.filter((c) => !evidenceIds.has(c.chunk_id));
  const grounded = citedIds.size > 0;
  const entries = r.audit_entries ?? [];

  return (
    <div {...testid(TID.runDetail)}>
      <PageHead
        eyebrow="Act 3 · propose, pause, and only then write"
        title="Workflow run"
        subtitle={
          <>
            <CopyId id={r.id} />
            {r.agent_version && <span className="faint"> · {r.agent_version}</span>}
            {r.eval_batch_id && (
              <span className="badge badge--accent" style={{ marginLeft: "var(--sp-2)" }}>
                eval batch
              </span>
            )}
          </>
        }
        actions={
          <>
            <RunBadge status={r.status} {...testid(TID.runStatus)} />
            {r.status === "awaiting_approval" && (
              <Link to="/approvals" className="btn btn--primary">
                Open approval
              </Link>
            )}
          </>
        }
      />

      <div className="stack">
        <Panel>
          <Timeline status={r.status} />
          {isActive(r.status) && (
            <p className="faint" style={{ fontSize: "var(--fs-xs)", marginTop: "var(--sp-3)" }}>
              Live — this page refreshes itself until the run settles.
            </p>
          )}
        </Panel>

        {r.status === "failed" && (
          <div className="banner banner--err" role="alert">
            <div>
              <strong>{r.failure_reason ?? "failed"}</strong>
              {r.failure_reason === "ungrounded" && (
                <p style={{ marginTop: 4 }}>
                  The model produced an answer with no usable citation, so the run was failed
                  rather than reported. Evidence retrieved for it is kept below — that is the
                  diagnosis.
                </p>
              )}
              {r.error && <p className="mono" style={{ marginTop: 4 }}>{r.error}</p>}
            </div>
          </div>
        )}

        <div className="grid grid--2">
          <Panel title="Triage result">
            {Object.keys(output).length === 0 ? (
              <p className="faint">No structured output — the run did not get that far.</p>
            ) : (
              <dl className="dl">
                <dt>Category</dt>
                <dd {...testid(TID.runField("category"))}>
                  <Maybe value={output.category} />
                </dd>
                <dt>Urgency</dt>
                <dd {...testid(TID.runField("urgency"))}>
                  <Maybe value={output.urgency} />
                </dd>
                <dt>Team</dt>
                <dd {...testid(TID.runField("recommended_team"))}>
                  <Maybe value={output.recommended_team} />
                </dd>
                <dt>Priority</dt>
                <dd {...testid(TID.runField("suggested_priority"))}>
                  <Maybe value={output.suggested_priority} />
                </dd>
                <dt>Confidence</dt>
                <dd {...testid(TID.runConfidence)}>
                  {r.confidence === null || r.confidence === undefined
                    ? "—"
                    : r.confidence.toFixed(2)}
                </dd>
                <dt>Grounded</dt>
                <dd>
                  {grounded ? (
                    <span className="badge badge--ok">
                      <span className="badge__dot" />
                      {citedIds.size} cited source{citedIds.size === 1 ? "" : "s"}
                    </span>
                  ) : (
                    <span className="badge badge--err">
                      <span className="badge__dot" />
                      not grounded
                    </span>
                  )}
                </dd>
              </dl>
            )}

            {output.summary && (
              <>
                <hr className="divider" />
                <div className="metric__label">Summary</div>
                <p style={{ marginTop: "var(--sp-2)" }}>{output.summary}</p>
              </>
            )}

            {output.recommended_resolution && (
              <>
                <hr className="divider" />
                <div className="metric__label">Recommended resolution</div>
                <p style={{ marginTop: "var(--sp-2)" }} {...testid(TID.runResolution)}>
                  {output.recommended_resolution}
                </p>
              </>
            )}
          </Panel>

          <Panel title="Ticket">
            {ticket.isPending && <Loading rows={3} />}
            {ticket.data && (
              <dl className="dl">
                <dt>Title</dt>
                <dd>
                  <Link to={`/tickets`}>{ticket.data.title}</Link>
                </dd>
                <dt>Status</dt>
                <dd>{ticket.data.status}</dd>
                <dt>Service</dt>
                <dd>
                  <Maybe value={ticket.data.service} />
                </dd>
                <dt>Department</dt>
                <dd>
                  <Maybe value={ticket.data.department} />
                </dd>
                <dt>Priority</dt>
                <dd>
                  <Maybe value={ticket.data.priority} />
                </dd>
                <dt>Team</dt>
                <dd>
                  <Maybe value={ticket.data.assigned_team} />
                </dd>
                <dt>Started</dt>
                <dd className="muted">{formatDateTime(r.started_at)}</dd>
                <dt>Finished</dt>
                <dd className="muted">{formatDateTime(r.finished_at)}</dd>
              </dl>
            )}
          </Panel>
        </div>

        {(output.executed_actions?.length ?? 0) > 0 && (
          <Panel title="Executed actions" {...testid(TID.runProposal)}>
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Tool</th>
                    <th>Field</th>
                    <th>From</th>
                    <th>To</th>
                  </tr>
                </thead>
                <tbody>
                  {(output.executed_actions ?? []).map((action, i) => (
                    <tr key={i}>
                      <td>
                        <Mono>{action.tool}</Mono>
                      </td>
                      <td className="muted">{action.field ?? "—"}</td>
                      <td className="muted">{String(action.current_value ?? "—")}</td>
                      <td>{String(action.new_value ?? "—")}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>
        )}

        <Panel
          title={
            <>
              <span>Evidence</span>
              <span className="faint" style={{ fontSize: "var(--fs-xs)", fontWeight: 400 }}>
                {evidence.length} retrieved · {citedIds.size} cited
              </span>
            </>
          }
          {...testid(TID.evidencePanel)}
        >
          {unresolved.length > 0 && (
            <div className="banner banner--warn" style={{ marginBottom: "var(--sp-3)" }} role="alert">
              <div>
                <strong>
                  {unresolved.length} citation{unresolved.length === 1 ? "" : "s"} could not be
                  resolved
                </strong>
                <p style={{ marginTop: 4 }}>
                  The model cited a chunk that is not in this run&apos;s retrieved evidence, so it
                  supports nothing. Shown rather than hidden — a citation that cannot be checked is
                  the thing worth seeing.
                </p>
                <div style={{ marginTop: "var(--sp-2)" }}>
                  {unresolved.map((c) => (
                    <div
                      key={c.chunk_id}
                      className="mono"
                      style={{ fontSize: "var(--fs-xs)" }}
                      {...testid(TID.citationUnresolved(c.chunk_id))}
                    >
                      {c.chunk_id}
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}

          {evidence.length === 0 ? (
            <Empty
              title="No evidence retrieved"
              body="Retrieval returned nothing for this ticket. With an empty corpus that is expected, and the run fails as ungrounded by design."
            />
          ) : (
            <>
              <div className="evidence" {...testid(TID.citationList)}>
                {/* Cited chunks first: the ones that carry the recommendation
                    should not be hunted for in a list of five. */}
                {[...evidence]
                  .sort((a, b) => Number(citedIds.has(b.chunk_id)) - Number(citedIds.has(a.chunk_id)))
                  .map((chunk) => {
                    const cited = citedIds.has(chunk.chunk_id);
                    return (
                      <div
                        key={chunk.chunk_id}
                        // `citation-<id>` marks a chunk the model actually
                        // cited — not merely one that retrieval returned. That
                        // distinction is the whole point of the panel, and it
                        // was wrong here: the id sat on all five retrieved
                        // chunks, so "every citation resolves to evidence" was
                        // trivially true and G6.3 could not have failed.
                        // Retrieved-but-uncited chunks carry `evidence-<id>`
                        // alone, which is what that id is for.
                        {...(cited ? testid(TID.citation(chunk.chunk_id)) : {})}
                      >
                        <EvidenceItem chunk={chunk} cited={cited} />
                      </div>
                    );
                  })}
              </div>
            </>
          )}
        </Panel>

        <Panel
          title={
            <>
              <span>Audit trail</span>
              <span className="faint" style={{ fontSize: "var(--fs-xs)", fontWeight: 400 }}>
                {entries.length} {entries.length === 1 ? "entry" : "entries"}
              </span>
            </>
          }
          flush
          {...testid(TID.runAudit)}
        >
          {entries.length === 0 ? (
            <p className="faint" style={{ padding: "var(--sp-4)" }}>
              No audit entries for this run yet.
            </p>
          ) : (
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Actor</th>
                    <th>Tool</th>
                    <th className="num">Latency</th>
                    <th className="num">Tokens</th>
                    <th>When</th>
                  </tr>
                </thead>
                <tbody>
                  {entries.map((entry, i) => (
                    <tr key={`${entry.tool}-${entry.created_at}-${i}`}>
                      <td>
                        <Mono>{entry.actor.startsWith("user:") ? "human" : entry.actor}</Mono>
                      </td>
                      <td>
                        <Mono>{entry.tool}</Mono>
                      </td>
                      <td className="num muted">
                        {entry.latency_ms === null ? "—" : `${entry.latency_ms}ms`}
                      </td>
                      <td className="num muted">
                        {(entry.tokens_in ?? 0) + (entry.tokens_out ?? 0) || "—"}
                      </td>
                      <td className="muted">{formatDateTime(entry.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Panel>
      </div>
    </div>
  );
}
