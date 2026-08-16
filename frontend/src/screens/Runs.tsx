/**
 * Runs list — the index for the run-detail screen.
 *
 * Eval runs are hidden by default and revealed by a toggle. A twenty-ticket
 * batch adds twenty runs at once and none of them is work a person requested,
 * so mixing them into the default view buries the one run somebody is actually
 * waiting on.
 */

import { useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { useRuns } from "../api/hooks";
import {
  Empty,
  ErrorState,
  Loading,
  Mono,
  PageHead,
  Panel,
  RunBadge,
  ShortId,
  timeAgo,
} from "../components/ui";
import { useTitle } from "../shell/Shell";
import { TID, testid } from "../testids";

const PAGE = 50;
const STATUSES = [
  "queued",
  "running",
  "awaiting_approval",
  "executing",
  "completed",
  "rejected",
  "failed",
];

export function Runs() {
  useTitle("Runs");
  const [status, setStatus] = useState("");
  const [includeEval, setIncludeEval] = useState(false);
  const [offset, setOffset] = useState(0);

  const filters = useMemo(
    () => ({
      status: status || undefined,
      include_eval: includeEval || undefined,
      limit: PAGE,
      offset,
    }),
    [status, includeEval, offset],
  );

  const runs = useRuns(filters);
  const total = runs.data?.total ?? 0;
  const rows = runs.data?.runs ?? [];

  return (
    <div>
      <PageHead
        title="Runs"
        subtitle="Every triage execution, and what happened to it."
      />

      <Panel
        flush
        title={
          <div className="filters" style={{ flex: 1 }}>
            <select
              className="select"
              value={status}
              onChange={(e) => {
                setStatus(e.target.value);
                setOffset(0);
              }}
              aria-label="Filter by status"
            >
              <option value="">All statuses</option>
              {STATUSES.map((s) => (
                <option key={s} value={s}>
                  {s.replace(/_/g, " ")}
                </option>
              ))}
            </select>
            <label className="row" style={{ fontSize: "var(--fs-sm)", cursor: "pointer" }}>
              <input
                type="checkbox"
                checked={includeEval}
                onChange={(e) => {
                  setIncludeEval(e.target.checked);
                  setOffset(0);
                }}
              />
              Include eval runs
            </label>
            <span className="faint" style={{ fontSize: "var(--fs-xs)" }}>
              {total} runs
            </span>
          </div>
        }
      >
        {runs.isPending && <Loading label="Loading runs" />}
        {runs.isError && <ErrorState error={runs.error} onRetry={() => void runs.refetch()} />}
        {runs.data && rows.length === 0 && (
          <Empty
            title="No runs"
            body={
              status
                ? "No runs in that status."
                : "Start triage from a ticket and it will appear here."
            }
            action={
              <Link to="/tickets" className="btn btn--primary">
                Go to tickets
              </Link>
            }
          />
        )}

        {rows.length > 0 && (
          <>
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Run</th>
                    <th>Status</th>
                    <th>Version</th>
                    <th className="num">Confidence</th>
                    <th>Failure</th>
                    <th>Started</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {rows.map((run) => (
                    <tr key={run.id}>
                      <td>
                        <Link to={`/runs/${run.id}`}>
                          <ShortId id={run.id} />
                        </Link>
                        {run.eval_batch_id && (
                          <span className="badge badge--accent" style={{ marginLeft: 6 }}>
                            eval
                          </span>
                        )}
                      </td>
                      <td>
                        <RunBadge status={run.status} />
                      </td>
                      <td className="muted">
                        <Mono>{run.agent_version ?? "—"}</Mono>
                      </td>
                      <td className="num muted">
                        {run.confidence === null || run.confidence === undefined
                          ? "—"
                          : run.confidence.toFixed(2)}
                      </td>
                      <td className="muted">
                        {run.failure_reason ? (
                          <span className="badge badge--err">{run.failure_reason}</span>
                        ) : (
                          "—"
                        )}
                      </td>
                      <td className="muted">{timeAgo(run.started_at ?? run.created_at)}</td>
                      <td style={{ textAlign: "right" }}>
                        <Link to={`/runs/${run.id}`} className="btn btn--sm">
                          Open
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="pagination">
              <span>
                {offset + 1}–{Math.min(offset + PAGE, total)} of {total}
              </span>
              <span className="pagination__spacer" />
              <button
                type="button"
                className="btn btn--sm"
                disabled={offset === 0}
                onClick={() => setOffset(Math.max(0, offset - PAGE))}
              >
                Previous
              </button>
              <button
                type="button"
                className="btn btn--sm"
                disabled={offset + PAGE >= total}
                onClick={() => setOffset(offset + PAGE)}
              >
                Next
              </button>
            </div>
          </>
        )}
      </Panel>
    </div>
  );
}
