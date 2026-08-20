/**
 * Approval inbox (spec 07 screen 8) — the human gate.
 *
 * The card contents are fixed by the personas doc: proposed action, affected
 * ticket, new vs existing values, evidence, confidence, risk class, agent
 * version. All of it, because an approver asked to authorise a write with
 * anything missing is being asked to rubber-stamp.
 *
 * **Only an Approver may decide.** `POST /decision` carries APPROVER_ONLY
 * server-side — an administrator reading this screen sees the same card and no
 * buttons, which is segregation of duties made visible (CLAUDE.md: proposer and
 * authoriser must be different actors).
 */

import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { useAgentConfig, useApproval, useApprovals, useDecide, useRun, useTicket } from "../api/hooks";
import type { AgentConfig, Approval, ProposedAction } from "../api/types";
import {
  Badge,
  Empty,
  ErrorState,
  Loading,
  Maybe,
  Modal,
  Mono,
  PageHead,
  Panel,
  ShortId,
  timeAgo,
} from "../components/ui";
import { useToast } from "../components/Toast";
import { useHasRole, useTitle } from "../shell/Shell";
import { TID, testid } from "../testids";

const riskTone = (risk?: string | null) =>
  risk === "high" ? "err" : risk === "medium" ? "warn" : "ok";

export function Approvals() {
  useTitle("Approvals");
  const approvals = useApprovals();
  const [selected, setSelected] = useState<string | null>(null);

  const pending = approvals.data?.filter((a) => a.status === "pending") ?? [];

  // Select the first pending item automatically — an inbox that opens empty
  // when there is work waiting makes the approver click twice for no reason.
  useEffect(() => {
    if (!selected && pending.length > 0) setSelected(pending[0]!.id);
    if (selected && !pending.some((a) => a.id === selected)) {
      setSelected(pending[0]?.id ?? null);
    }
  }, [pending, selected]);

  return (
    <div {...testid(TID.approvalInbox)}>
      <PageHead
        eyebrow="Act 4 · a person decides"
        title="Approval inbox"
        subtitle="The agent proposes; a person decides. Nothing is written to the ticket system until it is approved here."
      />

      {approvals.isPending && <Loading label="Loading approvals" />}
      {approvals.isError && (
        <ErrorState error={approvals.error} onRetry={() => void approvals.refetch()} />
      )}

      {approvals.data && pending.length === 0 && (
        <Empty
          title="Nothing waiting"
          body="No proposed actions need a decision right now. Runs that reach a proposal will appear here within seconds."
        />
      )}

      {pending.length > 0 && (
        <div className="grid" style={{ gridTemplateColumns: "minmax(280px, 340px) 1fr" }}>
          <Panel title={`Pending (${pending.length})`} flush>
            <div className="table-wrap">
              <table className="table table--clickable">
                <tbody>
                  {pending.map((approval) => (
                    <tr
                      key={approval.id}
                      onClick={() => setSelected(approval.id)}
                      aria-selected={approval.id === selected}
                      {...testid(TID.approvalRow(approval.id))}
                    >
                      <td>
                        <div className="row" style={{ gap: "var(--sp-2)" }}>
                          <Badge tone={riskTone(approval.risk_class)}>
                            {approval.risk_class ?? "low"}
                          </Badge>
                          <ShortId id={approval.run_id} />
                        </div>
                        {/* Deliberately not an action count: the list payload
                            omits `original_proposal`, so counting it here
                            renders a confident "0 actions" next to a card
                            showing three. Say what the list actually knows. */}
                        <div className="faint" style={{ fontSize: "var(--fs-xs)", marginTop: 2 }}>
                          waiting {timeAgo(approval.created_at).replace(" ago", "")}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>

          {selected ? <ApprovalCard approvalId={selected} /> : <Panel>Select an approval.</Panel>}
        </div>
      )}
    </div>
  );
}

function ApprovalCard({ approvalId }: { approvalId: string }) {
  const approval = useApproval(approvalId);
  const canDecide = useHasRole("approver");
  const decide = useDecide(approvalId);
  const toast = useToast();
  const run = useRun(approval.data?.run_id);
  // Fetched here so the taxonomy is warm before anyone opens the edit form —
  // validation that cannot name the allowed values is validation that passes
  // everything.
  const config = useAgentConfig();
  // The approval carries `ticket_id`; fall back to the run when an older
  // payload omits it, so the card still names its subject. Resolved before the
  // early returns below — a hook behind a conditional return is a hook that
  // changes order between renders.
  const ticketId = approval.data?.ticket_id ?? run.data?.ticket_id ?? null;
  const ticket = useTicket(ticketId ?? undefined);
  const [mode, setMode] = useState<"edit" | "reject" | null>(null);

  if (approval.isPending) return <Panel><Loading rows={6} /></Panel>;
  if (approval.isError)
    return (
      <Panel>
        <ErrorState error={approval.error} onRetry={() => void approval.refetch()} />
      </Panel>
    );
  if (!approval.data) return <Panel><Empty title="Approval not found" /></Panel>;

  const a = approval.data;
  const actions = a.original_proposal ?? [];

  return (
    <div className="stack" {...testid(TID.approvalCard)}>
      <Panel
        title={
          <>
            <span>Proposed action</span>
            <Badge tone={riskTone(a.risk_class)} {...testid(TID.approvalRisk)}>
              {a.risk_class ?? "low"} risk
            </Badge>
            <Link to={`/runs/${a.run_id}`} className="btn btn--ghost btn--sm" style={{ marginLeft: "auto" }}>
              View full run
            </Link>
          </>
        }
      >
        <dl className="dl">
          {/* The affected ticket, first. The personas doc lists it among the
              approval card's required contents, and it was missing: an
              approver was being asked to authorise a priority or team write
              without being told which ticket would change. */}
          <dt>Ticket</dt>
          <dd {...testid(TID.approvalTicket)}>
            {ticket.data ? (
              <>
                <Link to="/tickets">{ticket.data.title}</Link>
                {ticket.data.service && <span className="faint"> · {ticket.data.service}</span>}
              </>
            ) : (
              <span className="faint">loading…</span>
            )}
            <div className="mono faint" style={{ fontSize: "var(--fs-xs)", marginTop: 2 }}>
              {ticketId ?? "unknown ticket"}
            </div>
          </dd>
          <dt>Run</dt>
          <dd>
            <Link to={`/runs/${a.run_id}`}>
              <ShortId id={a.run_id} />
            </Link>
          </dd>
          <dt>Confidence</dt>
          <dd {...testid(TID.approvalConfidence)}>
            {a.confidence === null || a.confidence === undefined ? "—" : a.confidence.toFixed(2)}
          </dd>
          <dt>Agent version</dt>
          <dd {...testid(TID.approvalAgentVersion)}>
            <Mono>
              <Maybe value={a.agent_version} />
            </Mono>
          </dd>
        </dl>

        <hr className="divider" />

        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Tool</th>
                <th>Field</th>
                <th>Current</th>
                <th>Proposed</th>
              </tr>
            </thead>
            <tbody>
              {actions.map((action, i) => (
                <tr key={i} {...testid(TID.approvalProposal(i))}>
                  <td>
                    <Mono>{action.tool}</Mono>
                  </td>
                  <td className="muted">{action.field ?? "—"}</td>
                  <td className="muted" {...testid(TID.approvalCurrentValue(i))}>
                    {action.current_value === null || action.current_value === undefined
                      ? "not set"
                      : String(action.current_value)}
                  </td>
                  <td {...testid(TID.approvalNewValue(i))}>
                    <strong>{String(action.new_value ?? "—")}</strong>
                  </td>
                </tr>
              ))}
              {actions.length === 0 && (
                <tr>
                  <td colSpan={4} className="faint">
                    No structured proposal recorded.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        {a.status === "decided" ? (
          <div className="banner banner--info" style={{ marginTop: "var(--sp-4)" }}>
            Already decided: <strong>{a.decision}</strong>
            {a.feedback && <> — {a.feedback}</>}
          </div>
        ) : canDecide ? (
          <div className="row" style={{ marginTop: "var(--sp-4)", gap: "var(--sp-2)" }}>
            <button
              type="button"
              className="btn btn--primary"
              disabled={decide.isPending}
              onClick={() =>
                decide.mutate(
                  { decision: "approved" },
                  {
                    // The write happens in a worker, on a screen the approver
                    // is about to leave. Without this the only feedback is a
                    // row quietly changing somewhere else.
                    onSuccess: () =>
                      toast({
                        tone: "ok",
                        title: "Approved",
                        body: "The run resumed; the write executes against the ticket system now.",
                      }),
                    onError: (e) =>
                      toast({
                        tone: "err",
                        title: "Could not approve",
                        body: e instanceof Error ? e.message : undefined,
                      }),
                  },
                )
              }
              {...testid(TID.approve)}
            >
              {decide.isPending ? "Working…" : "Approve"}
            </button>
            <button
              type="button"
              className="btn"
              disabled={decide.isPending}
              onClick={() => setMode("edit")}
              {...testid(TID.openEdit)}
            >
              Edit
            </button>
            <button
              type="button"
              className="btn btn--danger"
              disabled={decide.isPending}
              onClick={() => setMode("reject")}
              {...testid(TID.openReject)}
            >
              Reject
            </button>
          </div>
        ) : (
          <div className="banner banner--warn" style={{ marginTop: "var(--sp-4)" }}>
            Read-only. Only an <strong>Approver</strong> may decide — the agent proposes and a
            different person authorises, which is the segregation of duties this system is built
            around.
          </div>
        )}

        {decide.isError && (
          <div
            className="banner banner--err"
            style={{ marginTop: "var(--sp-3)" }}
            role="alert"
            {...testid(TID.decisionError)}
          >
            {decide.error instanceof Error ? decide.error.message : "Could not record the decision"}
          </div>
        )}
      </Panel>

      <EvidenceSummary runId={a.run_id} />

      {mode === "edit" && (
        <EditModal
          actions={actions}
          taxonomy={config.data?.taxonomy}
          pending={decide.isPending}
          onClose={() => setMode(null)}
          onSubmit={(final) =>
            decide.mutate(
              { decision: "edited", final_values: final },
              {
                onSuccess: () => {
                  setMode(null);
                  toast({
                    tone: "ok",
                    title: "Approved with edits",
                    body: "Both the agent's proposal and your edit are in the audit record.",
                  });
                },
              },
            )
          }
        />
      )}
      {mode === "reject" && (
        <RejectModal
          pending={decide.isPending}
          onClose={() => setMode(null)}
          onSubmit={(feedback) =>
            decide.mutate(
              { decision: "rejected", feedback },
              {
                onSuccess: () => {
                  setMode(null);
                  toast({
                    tone: "info",
                    title: "Rejected",
                    body: "No write reached the ticket system. Your feedback is on the run.",
                  });
                },
              },
            )
          }
        />
      )}
    </div>
  );
}

/** The evidence the approver is being asked to trust, read from the run itself. */
function EvidenceSummary({ runId }: { runId: string }) {
  const run = useRun(runId);
  const evidence = run.data?.evidence ?? [];
  const cited = new Set((run.data?.output?.citations ?? []).map((c) => c.chunk_id));

  return (
    <Panel
      title={
        <>
          <span>Evidence</span>
          <span className="faint" style={{ fontSize: "var(--fs-xs)", fontWeight: 400 }}>
            {cited.size} cited of {evidence.length} retrieved
          </span>
        </>
      }
    >
      {run.isPending && <Loading rows={3} />}
      {evidence.length === 0 && !run.isPending && (
        <p className="faint">No evidence recorded for this run.</p>
      )}
      <div className="evidence">
        {evidence
          .filter((c) => cited.has(c.chunk_id))
          .map((chunk) => (
            <div key={chunk.chunk_id} className="evidence__item evidence__item--cited">
              <div className="evidence__head">
                <span className="evidence__title">{chunk.document_title ?? "Untitled"}</span>
                <span className="evidence__loc">
                  {[chunk.page ? `p.${chunk.page}` : null, chunk.section].filter(Boolean).join(" · ")}
                </span>
              </div>
              {chunk.text && <p className="evidence__text">{chunk.text}</p>}
            </div>
          ))}
      </div>
      {run.data?.output?.recommended_resolution && (
        <>
          <hr className="divider" />
          <div className="metric__label">Recommended resolution</div>
          <p style={{ marginTop: "var(--sp-2)" }}>{run.data.output.recommended_resolution}</p>
        </>
      )}
    </Panel>
  );
}

/**
 * Allowed values per proposed field, from the same taxonomy the agent's own
 * output is validated against. A field with no governed set (an internal note)
 * is free text and only has to be non-empty.
 */
function allowedFor(
  field: string | null | undefined,
  taxonomy: AgentConfig["taxonomy"] | undefined,
): string[] | null {
  if (!taxonomy) return null;
  switch (field) {
    case "priority":
      return taxonomy.priorities;
    case "assigned_team":
      return taxonomy.teams;
    case "category":
      return taxonomy.categories;
    case "urgency":
      return taxonomy.urgencies;
    default:
      return null;
  }
}

function EditModal({
  actions,
  taxonomy,
  pending,
  onClose,
  onSubmit,
}: {
  actions: ProposedAction[];
  taxonomy: AgentConfig["taxonomy"] | undefined;
  pending: boolean;
  onClose: () => void;
  onSubmit: (final: ProposedAction[]) => void;
}) {
  const [values, setValues] = useState(actions.map((a) => String(a.new_value ?? "")));
  const [touched, setTouched] = useState(false);
  const changed = values.some((v, i) => v !== String(actions[i]?.new_value ?? ""));

  /**
   * Validation before authorisation, not after.
   *
   * This form used to accept any string that differed from the proposal, so an
   * approver could authorise `P99-not-a-priority` and the client would POST it
   * — the "validated form" the screen contract promises was a diff check. An
   * out-of-taxonomy value is refused here; the server validates independently
   * and remains the enforcer.
   */
  const errors = actions.map((action, i) => {
    const value = (values[i] ?? "").trim();
    if (value === "") return "This value cannot be empty.";
    const allowed = allowedFor(action.field, taxonomy);
    if (allowed === null) {
      // An enum field whose taxonomy has not loaded must not be waved through:
      // "we could not check" is not "it is fine".
      const governed = ["priority", "assigned_team", "category", "urgency"];
      if (action.field && governed.includes(action.field)) {
        return "Waiting for the agent taxonomy before this value can be checked.";
      }
      return null;
    }
    if (!allowed.includes(value)) {
      return `Not a valid ${action.field}. Allowed: ${allowed.join(", ")}.`;
    }
    return null;
  });
  const valid = errors.every((e) => e === null);

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    setTouched(true);
    if (!valid) return;
    // Both proposals survive: the original is already stored on the approval,
    // and the edited values go alongside it so the audit trail can show what a
    // human changed and why (G6.4).
    onSubmit(
      actions.map((action, i) => ({
        ...action,
        new_value: (values[i] ?? "").trim(),
        args: { ...(action.args ?? {}), [String(action.field ?? "value")]: (values[i] ?? "").trim() },
      })),
    );
  };

  return (
    <Modal
      title="Edit proposed action"
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button
            type="submit"
            form="edit-approval"
            className="btn btn--primary"
            disabled={pending || !changed}
            {...testid(TID.editSubmit)}
          >
            {pending ? "Saving…" : "Approve with edits"}
          </button>
        </>
      }
    >
      <form id="edit-approval" onSubmit={submit} className="stack" {...testid(TID.editForm)}>
        {actions.map((action, i) => {
          const allowed = allowedFor(action.field, taxonomy);
          const listId = `edit-allowed-${i}`;
          const error = touched ? errors[i] : null;
          return (
            <div className="field" key={i}>
              <label className="field__label" htmlFor={`edit-${i}`}>
                <Mono>{action.tool}</Mono> — {action.field ?? "value"}
              </label>
              {/* A datalist rather than a select: it offers the governed values
                  as an affordance while staying a text input, so a value typed
                  by hand is still checked rather than silently impossible. */}
              <input
                id={`edit-${i}`}
                className="input"
                list={allowed ? listId : undefined}
                value={values[i] ?? ""}
                aria-invalid={error ? "true" : undefined}
                onChange={(e) =>
                  setValues((prev) => prev.map((v, j) => (j === i ? e.target.value : v)))
                }
                {...testid(TID.editValue(i))}
              />
              {allowed && (
                <datalist id={listId}>
                  {allowed.map((option) => (
                    <option key={option} value={option} />
                  ))}
                </datalist>
              )}
              {error ? (
                <span className="field__error" {...testid(TID.editError(i))}>
                  {error}
                </span>
              ) : (
                <span className="field__hint">
                  Agent proposed <strong>{String(action.new_value ?? "—")}</strong>; current value is{" "}
                  {String(action.current_value ?? "not set")}.
                </span>
              )}
            </div>
          );
        })}
        <div className="banner banner--info">
          Both versions are kept. The audit record shows the agent&apos;s original proposal and
          your edit side by side.
        </div>
      </form>
    </Modal>
  );
}

function RejectModal({
  pending,
  onClose,
  onSubmit,
}: {
  pending: boolean;
  onClose: () => void;
  onSubmit: (feedback: string) => void;
}) {
  const [feedback, setFeedback] = useState("");
  const tooShort = feedback.trim().length < 5;

  return (
    <Modal
      title="Reject proposed action"
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button
            type="submit"
            form="reject-approval"
            className="btn btn--danger"
            disabled={pending || tooShort}
            {...testid(TID.rejectSubmit)}
          >
            {pending ? "Recording…" : "Reject"}
          </button>
        </>
      }
    >
      <form
        id="reject-approval"
        onSubmit={(e) => {
          e.preventDefault();
          if (!tooShort) onSubmit(feedback.trim());
        }}
        className="stack"
        {...testid(TID.rejectForm)}
      >
        <div className="field">
          <label className="field__label" htmlFor="reject-why">
            Why are you rejecting this?
          </label>
          <textarea
            id="reject-why"
            className="textarea"
            value={feedback}
            onChange={(e) => setFeedback(e.target.value)}
            placeholder="The cited policy does not cover contractor accounts."
            {...testid(TID.rejectFeedback)}
          />
          <span className="field__hint">
            Required. This is the signal that improves the agent, and it is recorded against the
            run permanently.
          </span>
        </div>
        <div className="banner banner--warn">
          No write reaches the ticket system. The run ends as <strong>rejected</strong>.
        </div>
      </form>
    </Modal>
  );
}
