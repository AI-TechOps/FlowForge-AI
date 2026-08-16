/**
 * Evaluation results (spec 07 screen 9). Administrator only.
 *
 * Batches are listed newest-first with `agent_version` as a first-class column,
 * because the point of storing batches rather than printing scores is that two
 * versions can be read side by side (G5.5). The `llm_provider` column is here
 * for the reason the backend added it: a fake-provider harness batch and a real
 * one both store the configured model name, and a table that cannot tell them
 * apart invites quoting noise as quality.
 */

import { useState } from "react";

import { useEvalBatch, useEvalBatches, useStartEvalBatch } from "../api/hooks";
import type { EvalSummary } from "../api/types";
import {
  Badge,
  Empty,
  ErrorState,
  Loading,
  Mono,
  PageHead,
  Panel,
  ShortId,
  pct,
  num,
  timeAgo,
} from "../components/ui";
import { useTitle } from "../shell/Shell";
import { TID, testid } from "../testids";

const batchTone = (status: string) =>
  status === "completed" ? "ok" : status === "failed" ? "err" : "info";

export function Evaluation() {
  useTitle("Evaluation");
  const batches = useEvalBatches();
  const start = useStartEvalBatch();
  const [selected, setSelected] = useState<string | null>(null);

  const current = selected ?? batches.data?.[0]?.id ?? null;

  return (
    <div {...testid(TID.evaluation)}>
      <PageHead
        eyebrow="Act 5 · measured against a labelled answer key"
        title="Evaluation"
        subtitle="The agent scored against a labelled seed set — deterministic per-field accuracy, plus a judge running on a different model family."
        actions={
          <button
            type="button"
            className="btn btn--primary"
            disabled={start.isPending}
            onClick={() => start.mutate()}
            {...testid(TID.evalRunBatch)}
          >
            {start.isPending ? "Starting…" : "Run evaluation"}
          </button>
        }
      />

      {start.isError && (
        <div className="banner banner--err" style={{ marginBottom: "var(--sp-4)" }} role="alert">
          {start.error instanceof Error ? start.error.message : "Could not start a batch"}
        </div>
      )}

      <div className="stack">
        <Panel title="Batches" flush>
          {batches.isPending && <Loading label="Loading batches" />}
          {batches.isError && (
            <ErrorState error={batches.error} onRetry={() => void batches.refetch()} />
          )}
          {batches.data?.length === 0 && (
            <Empty
              title="No evaluation batches yet"
              body="Run one to score the agent against the labelled seed tickets. A batch triages every seed, then scores it — a few minutes on real models."
            />
          )}
          {batches.data && batches.data.length > 0 && (
            <div className="table-wrap">
              <table className="table table--clickable">
                <thead>
                  <tr>
                    <th>Batch</th>
                    <th>Agent version</th>
                    <th>Provider / models</th>
                    <th>Status</th>
                    <th className="num">Tickets</th>
                    <th className="num">Overall</th>
                    <th className="num">Grounded</th>
                    <th className="num">hit@k</th>
                    <th>When</th>
                  </tr>
                </thead>
                <tbody>
                  {batches.data.map((batch) => (
                    <tr
                      key={batch.id}
                      onClick={() => setSelected(batch.id)}
                      aria-selected={batch.id === current}
                      {...testid(TID.evalBatchRow(batch.id))}
                    >
                      <td>
                        <ShortId id={batch.id} />
                      </td>
                      <td>
                        <Mono>{batch.agent_version}</Mono>
                      </td>
                      <td className="muted">
                        <Mono>
                          {batch.llm_provider ?? "?"} · {batch.triage_model}
                          {batch.judge_model ? ` → ${batch.judge_model}` : ""}
                        </Mono>
                      </td>
                      <td>
                        <Badge tone={batchTone(batch.status)} live={batch.status === "running"}>
                          {batch.status}
                        </Badge>
                      </td>
                      <td className="num muted">{batch.total_tickets}</td>
                      <td className="num">{pct(batch.summary?.accuracy_overall)}</td>
                      <td className="num muted">{pct(batch.summary?.grounded_rate)}</td>
                      <td className="num muted">{pct(batch.summary?.retrieval_hit_at_k)}</td>
                      <td className="muted">{timeAgo(batch.created_at ?? batch.started_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Panel>

        {current && <BatchDetail batchId={current} />}
      </div>
    </div>
  );
}

function Metric({ id, label, value, sub }: { id: string; label: string; value: string; sub?: string }) {
  return (
    <div className="metric" {...testid(TID.evalMetric(id))}>
      <div className="metric__label">{label}</div>
      <div className="metric__value">{value}</div>
      {sub && <div className="metric__sub">{sub}</div>}
    </div>
  );
}

function BatchDetail({ batchId }: { batchId: string }) {
  const batch = useEvalBatch(batchId);

  if (batch.isPending) return <Panel><Loading rows={5} /></Panel>;
  if (batch.isError)
    return (
      <Panel>
        <ErrorState error={batch.error} onRetry={() => void batch.refetch()} />
      </Panel>
    );
  if (!batch.data) return null;

  const s: EvalSummary = batch.data.summary ?? {};
  const results = batch.data.results ?? [];

  return (
    <div className="stack" {...testid(TID.evalBatchDetail)}>
      <div className="grid grid--metrics">
        <Metric id="accuracy_overall" label="Overall" value={pct(s.accuracy_overall)} sub="all three fields correct" />
        <Metric id="accuracy_category" label="Category" value={pct(s.accuracy_category)} />
        <Metric id="accuracy_urgency" label="Urgency" value={pct(s.accuracy_urgency)} />
        <Metric id="accuracy_recommended_team" label="Team" value={pct(s.accuracy_recommended_team)} />
        <Metric id="grounded_rate" label="Grounded" value={pct(s.grounded_rate)} />
        <Metric id="retrieval_hit_at_k" label="Retrieval hit@k" value={pct(s.retrieval_hit_at_k)} />
        <Metric
          id="judge_resolution"
          label="Judge · resolution"
          value={num(s.judge_resolution_quality_mean, 2)}
          sub={`of 5 · ${s.judged_tickets ?? 0} judged`}
        />
        <Metric
          id="judge_citation"
          label="Judge · citation"
          value={num(s.judge_citation_support_mean, 2)}
          sub="of 5"
        />
        <Metric id="failed_runs" label="Failed runs" value={String(s.failed_runs ?? 0)} />
      </div>

      <Panel
        title={
          <>
            <span>Per-ticket results</span>
            <span className="faint" style={{ fontSize: "var(--fs-xs)", fontWeight: 400 }}>
              {results.length} scored
            </span>
          </>
        }
        flush
      >
        {results.length === 0 ? (
          <p className="faint" style={{ padding: "var(--sp-4)" }}>
            No results recorded yet — the batch is still running.
          </p>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Seed</th>
                  <th>Field</th>
                  <th>Expected</th>
                  <th>Actual</th>
                  <th>Result</th>
                </tr>
              </thead>
              <tbody>
                {results.map((result) => {
                  const expected = result.expected as Record<string, unknown>;
                  const actual = (result.actual ?? {}) as Record<string, unknown>;
                  const labels = (expected.labels ?? expected) as Record<string, unknown>;
                  const fields = ["category", "urgency", "recommended_team"];
                  return fields.map((field, i) => {
                    const want = labels[field];
                    const got = actual[field];
                    const ok = want !== undefined && String(want) === String(got);
                    return (
                      <tr
                        key={`${result.id}-${field}`}
                        {...(i === 0 ? testid(TID.evalResultRow(result.seed_ref ?? result.id)) : {})}
                      >
                        <td>
                          {i === 0 ? (
                            <>
                              <Mono>{result.seed_ref ?? "—"}</Mono>
                              {result.failure_reason && (
                                <span className="badge badge--err" style={{ marginLeft: 6 }}>
                                  {result.failure_reason}
                                </span>
                              )}
                            </>
                          ) : null}
                        </td>
                        <td className="muted">{field.replace("recommended_", "")}</td>
                        <td className="muted">{want === undefined ? "—" : String(want)}</td>
                        <td>{got === undefined || got === null ? "—" : String(got)}</td>
                        <td>
                          <Badge tone={ok ? "ok" : "err"}>{ok ? "match" : "miss"}</Badge>
                        </td>
                      </tr>
                    );
                  });
                })}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </div>
  );
}
