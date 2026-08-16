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
  Icon,
  Loading,
  Mono,
  PageHead,
  Panel,
  ShortId,
  pct,
  num,
  timeAgo,
} from "../components/ui";
import { MetricCard } from "../components/MetricCard";
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
        <MetricCard
          testId={TID.evalMetric("accuracy_overall")}
          valueTestId={TID.evalMetricValue("accuracy_overall")}
          label="Overall"
          value={pct(s.accuracy_overall)}
          sub="all three fields correct"
          icon={Icon.target({ size: 15 })}
          tone="accent"
          ring={s.accuracy_overall ?? null}
        />
        <MetricCard
          testId={TID.evalMetric("accuracy_category")}
          valueTestId={TID.evalMetricValue("accuracy_category")}
          label="Category"
          value={pct(s.accuracy_category)}
          icon={Icon.ticket({ size: 15 })}
          tone="ok"
          ring={s.accuracy_category ?? null}
        />
        <MetricCard
          testId={TID.evalMetric("accuracy_urgency")}
          valueTestId={TID.evalMetricValue("accuracy_urgency")}
          label="Urgency"
          value={pct(s.accuracy_urgency)}
          icon={Icon.alert({ size: 15 })}
          tone="warn"
          ring={s.accuracy_urgency ?? null}
        />
        <MetricCard
          testId={TID.evalMetric("accuracy_recommended_team")}
          valueTestId={TID.evalMetricValue("accuracy_recommended_team")}
          label="Team"
          value={pct(s.accuracy_recommended_team)}
          icon={Icon.approval({ size: 15 })}
          tone="accent"
          ring={s.accuracy_recommended_team ?? null}
        />
        <MetricCard
          testId={TID.evalMetric("grounded_rate")}
          valueTestId={TID.evalMetricValue("grounded_rate")}
          label="Grounded"
          value={pct(s.grounded_rate)}
          sub="answers with ≥1 valid citation"
          icon={Icon.shield({ size: 15 })}
          tone="ok"
          ring={s.grounded_rate ?? null}
        />
        <MetricCard
          testId={TID.evalMetric("retrieval_hit_at_k")}
          valueTestId={TID.evalMetricValue("retrieval_hit_at_k")}
          label="Retrieval hit@k"
          value={pct(s.retrieval_hit_at_k)}
          icon={Icon.search({ size: 15 })}
          tone="accent"
          ring={s.retrieval_hit_at_k ?? null}
        />
        <MetricCard
          testId={TID.evalMetric("judge_resolution")}
          valueTestId={TID.evalMetricValue("judge_resolution")}
          label="Judge · resolution"
          value={num(s.judge_resolution_quality_mean, 2)}
          unit="/ 5"
          sub={`${s.judged_tickets ?? 0} judged`}
          icon={Icon.spark({ size: 15 })}
          tone="accent"
          ring={
            s.judge_resolution_quality_mean != null
              ? s.judge_resolution_quality_mean / 5
              : null
          }
        />
        <MetricCard
          testId={TID.evalMetric("judge_citation")}
          valueTestId={TID.evalMetricValue("judge_citation")}
          label="Judge · citation"
          value={num(s.judge_citation_support_mean, 2)}
          unit="/ 5"
          sub="does the citation support the answer"
          icon={Icon.document({ size: 15 })}
          tone="accent"
          ring={
            s.judge_citation_support_mean != null ? s.judge_citation_support_mean / 5 : null
          }
        />
        <MetricCard
          testId={TID.evalMetric("failed_runs")}
          valueTestId={TID.evalMetricValue("failed_runs")}
          label="Failed runs"
          value={String(s.failed_runs ?? 0)}
          sub="never produced a scoreable result"
          icon={Icon.alert({ size: 15 })}
          tone={(s.failed_runs ?? 0) > 0 ? "err" : "neutral"}
        />
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
