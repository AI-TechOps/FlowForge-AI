/**
 * The dashboard (spec 07 screen 2).
 *
 * Role-awareness here is *by absence*, not by branching. The API omits
 * `estimated_cost_usd` and `evaluation_accuracy` for non-administrators (D19
 * decision 6, as amended by D20), so this screen renders the keys it was given
 * and never decides who deserves what. If the server's rule changes, the UI
 * follows automatically, and a bug here cannot leak a figure the server
 * withheld.
 *
 * Every rate is `null` rather than `0.0` when its denominator is empty, and
 * that distinction is preserved all the way to the pixel: "no data yet" means
 * nothing has happened, "0.0%" would mean it happened and failed.
 *
 * **The charts are derived, not fetched.** There is no time-series endpoint, so
 * the activity chart buckets `/api/runs` by day client-side and the donut
 * counts real run outcomes. Nothing is padded or smoothed — a window with two
 * runs draws two runs, because a dashboard that invents a pleasing curve is
 * worse than one that admits it is early.
 */

import { useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { useAudit, useMetrics, useRuns } from "../api/hooks";
import type { MetricsSummary, Run } from "../api/types";
import {
  AreaChart,
  Donut,
  Legend,
  Ring,
  Sparkline,
  bucketCountsBy,
  bucketSeries,
  type Slice,
} from "../components/charts";
import {
  Empty,
  ErrorState,
  Icon,
  Loading,
  PageHead,
  Panel,
  RunBadge,
  ShortId,
  num,
  pct,
  timeAgo,
} from "../components/ui";
import { useHasRole, useTitle } from "../shell/Shell";
import { TID, testid } from "../testids";

const WINDOWS = [7, 30, 90] as const;

type Tone = "accent" | "ok" | "warn" | "err" | "neutral";

function Metric({
  id,
  label,
  value,
  unit,
  sub,
  icon,
  tone = "accent",
  spark,
  ring,
}: {
  id: string;
  label: string;
  value: string;
  unit?: string;
  sub?: string;
  icon: JSX.Element;
  tone?: Tone;
  spark?: number[];
  ring?: number | null;
}) {
  const empty = value === "—";
  return (
    <div className="metric" {...testid(TID.metric(id))}>
      <div className="metric__top">
        <span className={`metric__badge metric__badge--${tone === "accent" ? "accent" : tone}`}>
          {icon}
        </span>
        <div style={{ minWidth: 0, flex: 1 }}>
          <div className="metric__label">{label}</div>
          {/* An em-dash at 32px is a horizontal bar, which reads as a loading
              skeleton rather than "no data". Absent values say so in words. */}
          {empty ? (
            <div className="metric__value--empty" {...testid(TID.metricValue(id))}>
              No data yet
            </div>
          ) : (
            <div className="metric__value" {...testid(TID.metricValue(id))}>
              {value}
              {unit && <span className="metric__unit">{unit}</span>}
            </div>
          )}
        </div>
        {ring !== undefined && !empty && (
          <Ring value={ring} tone={tone === "neutral" ? "accent" : tone} />
        )}
      </div>
      {sub && <div className="metric__sub">{sub}</div>}
      {spark && spark.length > 1 && (
        <div className="metric__spark">
          <Sparkline values={spark} tone={tone === "neutral" ? "accent" : tone} />
        </div>
      )}
    </div>
  );
}

/** Who did a thing, from the audit row's actor shape. */
function actorFace(actor: string) {
  if (actor.startsWith("user:")) return { cls: "avatar avatar--sm", text: "H", label: "human" };
  if (actor === "judge") return { cls: "avatar avatar--sm avatar--judge", text: "J", label: "judge" };
  return { cls: "avatar avatar--sm avatar--agent", text: "A", label: actor };
}

export function Dashboard() {
  useTitle("Dashboard");
  const [windowDays, setWindowDays] = useState<number>(30);
  const isAdmin = useHasRole("administrator");

  const metrics = useMetrics(windowDays);
  // Enough history to fill the chart. The endpoint caps at 200, which is well
  // past what a 90-day demo window holds.
  const history = useRuns({ limit: 200, include_eval: true });
  const recent = useRuns({ limit: 6 });
  const audit = useAudit({ limit: 8 }, isAdmin);

  const m = metrics.data;
  const runs: Run[] = history.data?.runs ?? [];

  const chart = useMemo(() => {
    const { labels, keys, counts, grain } = bucketSeries(
      runs,
      (r) => r.created_at,
      Math.min(windowDays, 30),
    );
    const by = (p: (r: Run) => boolean) =>
      bucketCountsBy(runs, keys, (r) => r.created_at, p, grain);
    return {
      labels,
      grain,
      total: counts,
      completed: by((r) => r.status === "completed"),
      failed: by((r) => r.status === "failed"),
    };
  }, [runs, windowDays]);

  const outcomes: Slice[] = useMemo(() => {
    const by = new Map<string, number>();
    for (const r of runs) by.set(r.status, (by.get(r.status) ?? 0) + 1);
    const palette: Record<string, string> = {
      completed: "var(--viz-4)",
      awaiting_approval: "var(--viz-5)",
      failed: "var(--viz-6)",
      running: "var(--viz-1)",
      queued: "var(--viz-3)",
      executing: "var(--viz-2)",
      rejected: "var(--text-faint)",
    };
    return [...by.entries()]
      .sort((a, b) => b[1] - a[1])
      .map(([status, value]) => ({
        label: status.replace(/_/g, " "),
        value,
        color: palette[status] ?? "var(--viz-2)",
      }));
  }, [runs]);

  const hasHistory = chart.total.some((v) => v > 0);

  return (
    <div {...testid(TID.dashboard)}>
      <PageHead
        eyebrow="Overview · one governed system of record"
        title="Dashboard"
        subtitle="Triage throughput, grounding quality, and the human decisions behind every write."
        actions={
          <div className="segmented" {...testid(TID.windowSelect)}>
            {WINDOWS.map((d) => (
              <button
                key={d}
                type="button"
                className={
                  d === windowDays ? "segmented__item segmented__item--active" : "segmented__item"
                }
                onClick={() => setWindowDays(d)}
              >
                {d}d
              </button>
            ))}
          </div>
        }
      />

      {metrics.isPending && <Loading label="Loading metrics" />}
      {metrics.isError && <ErrorState error={metrics.error} onRetry={() => void metrics.refetch()} />}

      {m && (
        <div className="stack fade-in">
          <div className="grid grid--metrics">
            <Metric
              id="total_runs"
              label="Runs"
              value={String(m.total_runs)}
              sub={`last ${m.window_days} days`}
              icon={Icon.run({ size: 16 })}
              tone="accent"
              spark={chart.total}
            />
            <Metric
              id="successful_runs"
              label="Completed"
              value={String(m.successful_runs)}
              sub={m.total_runs ? `${pct(m.successful_runs / m.total_runs)} of runs` : undefined}
              icon={Icon.check({ size: 16 })}
              tone="ok"
              spark={chart.completed}
              ring={m.total_runs ? m.successful_runs / m.total_runs : null}
            />
            <Metric
              id="waiting_approvals"
              label="Awaiting approval"
              value={String(m.waiting_approvals)}
              sub="the human gate"
              icon={Icon.approval({ size: 16 })}
              tone={m.waiting_approvals > 0 ? "warn" : "neutral"}
            />
            <Metric
              id="failed_runs"
              label="Failed"
              value={String(m.failed_runs)}
              sub="ungrounded or errored"
              icon={Icon.alert({ size: 16 })}
              tone={m.failed_runs > 0 ? "err" : "neutral"}
              spark={chart.failed}
            />
            <Metric
              id="grounded_rate"
              label="Grounded"
              value={pct(m.grounded_rate)}
              sub="answers with ≥1 valid citation"
              icon={Icon.shield({ size: 16 })}
              tone="ok"
              ring={m.grounded_rate}
            />
            <Metric
              id="retrieval_success"
              label="Retrieval hit@k"
              value={pct(m.retrieval_success)}
              sub="label's document was retrieved"
              icon={Icon.target({ size: 16 })}
              tone="accent"
              ring={m.retrieval_success}
            />
            <Metric
              id="avg_latency_seconds"
              label="Avg latency"
              value={m.avg_latency_seconds === null ? "—" : num(m.avg_latency_seconds, 2)}
              unit={m.avg_latency_seconds === null ? undefined : "s"}
              sub="queued to finished"
              icon={Icon.clock({ size: 16 })}
              tone="neutral"
            />
            <Metric
              id="avg_tokens_per_run"
              label="Tokens / run"
              value={m.avg_tokens_per_run === null ? "—" : num(m.avg_tokens_per_run, 0)}
              sub="model calls including the judge"
              icon={Icon.spark({ size: 16 })}
              tone="accent"
            />
            <Metric
              id="tool_success_rate"
              label="Tool success"
              value={pct(m.tool_success_rate)}
              sub="the five MVP tools"
              icon={Icon.config({ size: 16 })}
              tone="ok"
              ring={m.tool_success_rate}
            />
            <Metric
              id="approval_rate"
              label="Approval rate"
              value={pct(m.approval_rate)}
              sub={
                m.approval_rate === null
                  ? "no decisions yet"
                  : `edited ${pct(m.human_edit_rate)} · rejected ${pct(m.human_rejection_rate)}`
              }
              icon={Icon.approval({ size: 16 })}
              tone="accent"
              ring={m.approval_rate}
            />
            {/* Administrator-only, and present only because the API sent them. */}
            {"evaluation_accuracy" in m && (
              <Metric
                id="evaluation_accuracy"
                label="Eval accuracy"
                value={pct(m.evaluation_accuracy)}
                sub="latest batch, all three fields"
                icon={Icon.evaluation({ size: 16 })}
                tone="accent"
                ring={m.evaluation_accuracy ?? null}
              />
            )}
            {"estimated_cost_usd" in m && (
              <Metric
                id="estimated_cost_usd"
                label="Estimated cost"
                value={`$${(m.estimated_cost_usd ?? 0).toFixed(4)}`}
                sub={m.cost_pricing_as_of ? `pricing as of ${m.cost_pricing_as_of}` : undefined}
                icon={Icon.coins({ size: 16 })}
                tone="neutral"
              />
            )}
          </div>

          <div className="grid grid--main">
            <Panel
              title={
                <>
                  <span>Run activity</span>
                  <span className="faint" style={{ fontSize: "var(--fs-xs)", fontWeight: 400 }}>
                    {chart.grain === "hour" ? "hourly, last 24 hours" : `daily, last ${Math.min(windowDays, 30)} days`}
                  </span>
                  <div className="panel__head-actions">
                    <span className="legend__item" style={{ fontSize: "var(--fs-xs)" }}>
                      <span className="legend__swatch" style={{ background: "var(--viz-1)" }} />
                      all
                    </span>
                    <span className="legend__item" style={{ fontSize: "var(--fs-xs)" }}>
                      <span className="legend__swatch" style={{ background: "var(--viz-4)" }} />
                      completed
                    </span>
                    <span className="legend__item" style={{ fontSize: "var(--fs-xs)" }}>
                      <span className="legend__swatch" style={{ background: "var(--viz-6)" }} />
                      failed
                    </span>
                  </div>
                </>
              }
              {...testid(TID.runsChart)}
            >
              {history.isPending ? (
                <Loading rows={5} />
              ) : hasHistory ? (
                <AreaChart
                  labels={chart.labels}
                  series={[
                    { key: "total", label: "All runs", color: "var(--viz-1)", values: chart.total },
                    {
                      key: "completed",
                      label: "Completed",
                      color: "var(--viz-4)",
                      values: chart.completed,
                    },
                    { key: "failed", label: "Failed", color: "var(--viz-6)", values: chart.failed },
                  ]}
                />
              ) : (
                <Empty
                  title="Nothing has run in this window"
                  body="Start triage from a ticket and the curve begins here."
                />
              )}
            </Panel>

            <Panel title="Run outcomes" {...testid(TID.categoryDonut)}>
              {outcomes.length === 0 ? (
                <Empty title="No runs yet" />
              ) : (
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: "var(--sp-5)",
                    flexWrap: "wrap",
                  }}
                >
                  <Donut slices={outcomes} centerLabel="runs" />
                  <Legend slices={outcomes} />
                </div>
              )}
            </Panel>
          </div>

          <div className="grid grid--main">
            <Panel
              title="Recent runs"
              flush
              actions={
                <Link to="/runs" className="btn btn--ghost btn--sm">
                  View all {Icon.arrowRight({ size: 13 })}
                </Link>
              }
              {...testid(TID.recentRuns)}
            >
              {recent.isPending && <Loading rows={4} />}
              {recent.data?.runs.length === 0 && (
                <Empty
                  title="No runs yet"
                  body="Triage a ticket to see it here."
                  action={
                    <Link to="/tickets" className="btn btn--primary">
                      Go to tickets
                    </Link>
                  }
                />
              )}
              {recent.data && recent.data.runs.length > 0 && (
                <div className="table-wrap">
                  <table className="table">
                    <thead>
                      <tr>
                        <th>Run</th>
                        <th>Status</th>
                        <th className="num">Confidence</th>
                        <th style={{ textAlign: "right" }}>Started</th>
                      </tr>
                    </thead>
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

            {isAdmin && (
              <Panel
                title="Activity"
                flush
                actions={
                  <Link to="/audit" className="btn btn--ghost btn--sm">
                    Audit log {Icon.arrowRight({ size: 13 })}
                  </Link>
                }
                {...testid(TID.activityFeed)}
              >
                {audit.isPending && <Loading rows={4} />}
                {audit.data?.entries.length === 0 && (
                  <Empty title="Nothing recorded yet" body="Every agent step and human decision appears here." />
                )}
                <div className="feed">
                  {(audit.data?.entries ?? []).map((entry) => {
                    const face = actorFace(entry.actor);
                    const tokens = (entry.tokens_in ?? 0) + (entry.tokens_out ?? 0);
                    return (
                      <div className="feed__item" key={entry.id}>
                        <span className={face.cls} title={entry.actor}>
                          {face.text}
                        </span>
                        <div className="feed__body">
                          <div className="feed__title">
                            <strong>{face.label}</strong>{" "}
                            <span className="mono muted">{entry.tool}</span>
                          </div>
                          <div className="feed__meta">
                            <span>{timeAgo(entry.created_at)}</span>
                            {entry.latency_ms !== null && <span>· {entry.latency_ms}ms</span>}
                            {tokens > 0 && <span>· {tokens} tokens</span>}
                            {entry.run_id && (
                              <Link to={`/runs/${entry.run_id}`} className="mono">
                                · {entry.run_id.slice(0, 8)}
                              </Link>
                            )}
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </Panel>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
