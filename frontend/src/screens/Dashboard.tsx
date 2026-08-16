/**
 * The dashboard (spec 07 screen 2).
 *
 * Role-awareness here is *by absence*, not by branching. The API omits
 * `estimated_cost_usd` and `evaluation_accuracy` for non-administrators (D19
 * decision 6, as amended by D20), so this screen renders the keys it was given
 * and never decides who deserves what. That is the honest arrangement: if the
 * server's rule changes, the UI follows automatically, and a bug here cannot
 * leak a figure the server withheld.
 *
 * Every rate is `null` rather than `0.0` when its denominator is empty, and
 * that distinction is preserved all the way to the pixel: "—" means nothing has
 * happened yet, "0.0%" would mean it happened and failed.
 */

import { Link } from "react-router-dom";

import { useMetrics, useRuns } from "../api/hooks";
import type { MetricsSummary } from "../api/types";
import {
  ErrorState,
  Loading,
  PageHead,
  Panel,
  RunBadge,
  ShortId,
  num,
  pct,
  timeAgo,
} from "../components/ui";
import { useTitle } from "../shell/Shell";
import { TID, testid } from "../testids";
import { useState } from "react";

const WINDOWS = [7, 30, 90];

function Metric({
  id,
  label,
  value,
  sub,
  muted = false,
}: {
  id: string;
  label: string;
  value: string;
  sub?: string;
  muted?: boolean;
}) {
  return (
    <div className="metric" {...testid(TID.metric(id))}>
      <div className="metric__label">{label}</div>
      {/* An em-dash at 30px is a horizontal bar, which reads as a loading
          skeleton rather than "no data". Absent values get their own smaller
          treatment and say so in words. */}
      {value === "—" ? (
        <div className="metric__value metric__value--empty" {...testid(TID.metricValue(id))}>
          No data yet
        </div>
      ) : (
        <div
          className={muted ? "metric__value metric__value--muted" : "metric__value"}
          {...testid(TID.metricValue(id))}
        >
          {value}
        </div>
      )}
      {sub && <div className="metric__sub">{sub}</div>}
    </div>
  );
}

function OutcomeChart({ m }: { m: MetricsSummary }) {
  const rows = [
    { label: "Completed", value: m.successful_runs, tone: "ok" as const },
    { label: "Awaiting approval", value: m.waiting_approvals, tone: "warn" as const },
    { label: "Failed", value: m.failed_runs, tone: "err" as const },
  ];
  // Scale against the largest bar, not the total: with 60 completed and 1
  // failed, scaling by total makes the failure invisible — and the failure is
  // the bar somebody needs to see.
  const peak = Math.max(1, ...rows.map((r) => r.value));

  return (
    <div className="bars" {...testid(TID.outcomeChart)}>
      {rows.map((row) => (
        <div className="bar" key={row.label}>
          <span className="muted">{row.label}</span>
          <span className="bar__track">
            {/* No fill at all for zero — `min-width` on the fill guarantees a
                count of 1 stays visible, and that same rule would otherwise
                draw a stub for a count of none. */}
            {row.value > 0 && (
              <span
                className={`bar__fill bar__fill--${row.tone}`}
                style={{ width: `${(row.value / peak) * 100}%` }}
              />
            )}
          </span>
          <span className="bar__value">{row.value}</span>
        </div>
      ))}
    </div>
  );
}

export function Dashboard() {
  useTitle("Dashboard");
  const [windowDays, setWindowDays] = useState(30);
  const metrics = useMetrics(windowDays);
  const recent = useRuns({ limit: 8 });

  const m = metrics.data;
  const isAdmin = m !== undefined && "estimated_cost_usd" in m;

  return (
    <div {...testid(TID.dashboard)}>
      <PageHead
        title="Dashboard"
        subtitle="Triage throughput, grounding quality and the human decisions behind every write."
        actions={
          <select
            className="select"
            style={{ width: 150 }}
            value={windowDays}
            onChange={(e) => setWindowDays(Number(e.target.value))}
            aria-label="Time window"
            {...testid(TID.windowSelect)}
          >
            {WINDOWS.map((d) => (
              <option key={d} value={d}>
                Last {d} days
              </option>
            ))}
          </select>
        }
      />

      {metrics.isPending && <Loading label="Loading metrics" />}
      {metrics.isError && <ErrorState error={metrics.error} onRetry={() => void metrics.refetch()} />}

      {m && (
        <div className="stack">
          <div className="grid grid--metrics">
            <Metric id="total_runs" label="Runs" value={String(m.total_runs)} sub={`last ${m.window_days} days`} />
            <Metric
              id="successful_runs"
              label="Completed"
              value={String(m.successful_runs)}
              sub={m.total_runs ? pct(m.successful_runs / m.total_runs) + " of runs" : undefined}
            />
            <Metric id="waiting_approvals" label="Awaiting approval" value={String(m.waiting_approvals)} sub="human gate" />
            <Metric id="failed_runs" label="Failed" value={String(m.failed_runs)} />
            <Metric
              id="grounded_rate"
              label="Grounded"
              value={pct(m.grounded_rate)}
              sub="answers with ≥1 valid citation"
              muted={m.grounded_rate === null}
            />
            <Metric
              id="retrieval_success"
              label="Retrieval hit@k"
              value={pct(m.retrieval_success)}
              muted={m.retrieval_success === null}
            />
            <Metric
              id="avg_latency_seconds"
              label="Avg latency"
              value={m.avg_latency_seconds === null ? "—" : `${num(m.avg_latency_seconds, 2)}s`}
              muted={m.avg_latency_seconds === null}
            />
            <Metric
              id="avg_tokens_per_run"
              label="Tokens / run"
              value={m.avg_tokens_per_run === null ? "—" : num(m.avg_tokens_per_run, 0)}
              muted={m.avg_tokens_per_run === null}
            />
            <Metric
              id="tool_success_rate"
              label="Tool success"
              value={pct(m.tool_success_rate)}
              muted={m.tool_success_rate === null}
            />
            <Metric
              id="approval_rate"
              label="Approval rate"
              value={pct(m.approval_rate)}
              sub={
                m.human_edit_rate !== null || m.human_rejection_rate !== null
                  ? `edited ${pct(m.human_edit_rate)} · rejected ${pct(m.human_rejection_rate)}`
                  : "no decisions yet"
              }
              muted={m.approval_rate === null}
            />
            {/* Administrator-only, and present only because the API sent them. */}
            {isAdmin && (
              <Metric
                id="evaluation_accuracy"
                label="Eval accuracy"
                value={pct(m.evaluation_accuracy)}
                sub="latest batch, all three fields"
                muted={m.evaluation_accuracy === null || m.evaluation_accuracy === undefined}
              />
            )}
            {isAdmin && (
              <Metric
                id="estimated_cost_usd"
                label="Estimated cost"
                value={`$${(m.estimated_cost_usd ?? 0).toFixed(4)}`}
                sub={m.cost_pricing_as_of ? `pricing as of ${m.cost_pricing_as_of}` : undefined}
              />
            )}
          </div>

          <div className="grid grid--2">
            <Panel title="Run outcomes">
              <OutcomeChart m={m} />
              {m.total_runs === 0 && (
                <p className="faint" style={{ marginTop: "var(--sp-3)", fontSize: "var(--fs-sm)" }}>
                  No runs in this window yet.
                </p>
              )}
            </Panel>

            <Panel
              title="Recent runs"
              flush
              actions={
                <Link to="/runs" className="btn btn--ghost btn--sm">
                  View all
                </Link>
              }
              {...testid(TID.recentRuns)}
            >
              {recent.isPending && <Loading rows={4} />}
              {recent.data?.runs.length === 0 && (
                <p className="faint" style={{ padding: "var(--sp-4)", fontSize: "var(--fs-sm)" }}>
                  Nothing has run yet. Start from Tickets.
                </p>
              )}
              {recent.data && recent.data.runs.length > 0 && (
                <div className="table-wrap">
                  <table className="table">
                    <tbody>
                      {recent.data.runs.map((run) => (
                        <tr key={run.id}>
                          <td>
                            <Link to={`/runs/${run.id}`}>
                              <ShortId id={run.id} />
                            </Link>
                          </td>
                          <td>
                            <RunBadge status={run.status} />
                          </td>
                          <td className="num muted">
                            {run.confidence === null || run.confidence === undefined
                              ? "—"
                              : run.confidence.toFixed(2)}
                          </td>
                          <td className="muted" style={{ textAlign: "right" }}>
                            {timeAgo(run.created_at ?? run.started_at)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </Panel>
          </div>
        </div>
      )}
    </div>
  );
}
