/**
 * Audit log (spec 07 screen 10). Administrator only.
 *
 * Every agent step, every tool call, every human decision, every model call
 * including the judge. Paginated with a hard ceiling server-side, because this
 * is the one table guaranteed to grow without limit.
 *
 * Rows expand to raw payload and result JSON rather than a prettified summary:
 * an audit trail's value is that it shows what actually happened, and a view
 * that reformats is a view that can misrepresent.
 */

import { Fragment, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { useAudit } from "../api/hooks";
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
  formatDateTime,
} from "../components/ui";
import { useTitle } from "../shell/Shell";
import { TID, testid } from "../testids";

const PAGE = 50;

/** Actor shape tells you who acted: `agent`, `judge`, or `user:<uuid>`. */
function ActorBadge({ actor }: { actor: string }) {
  if (actor.startsWith("user:")) {
    return (
      <Badge tone="accent" title={actor}>
        human
      </Badge>
    );
  }
  if (actor === "judge") return <Badge tone="info">judge</Badge>;
  return <Badge tone="neutral">{actor}</Badge>;
}

export function Audit() {
  useTitle("Audit log");
  const [actor, setActor] = useState("");
  const [tool, setTool] = useState("");
  const [runId, setRunId] = useState("");
  const [offset, setOffset] = useState(0);
  const [expanded, setExpanded] = useState<string | null>(null);

  const filters = useMemo(
    () => ({
      actor: actor || undefined,
      tool: tool || undefined,
      run_id: runId || undefined,
      limit: PAGE,
      offset,
    }),
    [actor, tool, runId, offset],
  );

  const audit = useAudit(filters);
  const total = audit.data?.total ?? 0;
  const entries = audit.data?.entries ?? [];

  const resetTo = (fn: () => void) => {
    fn();
    setOffset(0); // a filter change must not leave you on page 7 of 2
  };

  return (
    <div {...testid(TID.audit)}>
      <PageHead
        eyebrow="The record · every step, every actor"
        title="Audit log"
        subtitle="Every agent step, tool call, model call and human decision — the record that makes a run reconstructable."
      />

      <Panel
        flush
        title={
          <div className="filters" style={{ flex: 1 }}>
            <input
              className="input"
              placeholder="Actor (agent, judge…)"
              value={actor}
              onChange={(e) => resetTo(() => setActor(e.target.value))}
              aria-label="Filter by actor"
              {...testid(TID.auditFilterActor)}
            />
            <input
              className="input"
              placeholder="Tool"
              value={tool}
              onChange={(e) => resetTo(() => setTool(e.target.value))}
              aria-label="Filter by tool"
              {...testid(TID.auditFilterTool)}
            />
            <input
              className="input"
              style={{ minWidth: 260 }}
              placeholder="Run id"
              value={runId}
              onChange={(e) => resetTo(() => setRunId(e.target.value))}
              aria-label="Filter by run"
              {...testid(TID.auditFilterRun)}
            />
            {(actor || tool || runId) && (
              <button
                type="button"
                className="btn btn--ghost btn--sm"
                onClick={() =>
                  resetTo(() => {
                    setActor("");
                    setTool("");
                    setRunId("");
                  })
                }
              >
                Clear
              </button>
            )}
            <span className="faint" style={{ fontSize: "var(--fs-xs)" }} {...testid(TID.auditTotal)}>
              {total} entries
            </span>
          </div>
        }
      >
        {audit.isPending && <Loading label="Loading audit trail" />}
        {audit.isError && <ErrorState error={audit.error} onRetry={() => void audit.refetch()} />}
        {audit.data && entries.length === 0 && (
          <Empty
            title="No audit entries"
            body={
              actor || tool || runId
                ? "No entries match these filters."
                : "Nothing has run yet. Every agent step and human decision will appear here."
            }
          />
        )}

        {entries.length > 0 && (
          <>
            <div className="table-wrap">
              <table className="table table--clickable">
                <thead>
                  <tr>
                    <th style={{ width: 32 }} />
                    <th>Actor</th>
                    <th>Tool</th>
                    <th>Run</th>
                    <th className="num">Latency</th>
                    <th className="num">Tokens</th>
                    <th className="num">Cost</th>
                    <th>When</th>
                  </tr>
                </thead>
                <tbody>
                  {entries.map((entry) => {
                    const open = expanded === entry.id;
                    const failed =
                      typeof entry.result === "object" &&
                      entry.result !== null &&
                      "error" in (entry.result as Record<string, unknown>);
                    return (
                      // Keyed Fragment: a row and its expansion are two <tr>
                      // siblings, and React needs the key on the wrapper.
                      <Fragment key={entry.id}>
                        <tr
                          onClick={() => setExpanded(open ? null : entry.id)}
                          {...testid(TID.auditRow(entry.id))}
                        >
                          <td>
                            <span
                              style={{
                                display: "inline-block",
                                transform: open ? "rotate(90deg)" : "none",
                                transition: "transform 0.12s ease",
                                color: "var(--text-faint)",
                              }}
                              {...testid(TID.auditExpand(entry.id))}
                            >
                              {Icon.chevron({ size: 12 })}
                            </span>
                          </td>
                          <td>
                            <ActorBadge actor={entry.actor} />
                          </td>
                          <td>
                            <Mono>{entry.tool}</Mono>
                            {failed && (
                              <span className="badge badge--err" style={{ marginLeft: 6 }}>
                                error
                              </span>
                            )}
                          </td>
                          <td>
                            {entry.run_id ? (
                              <Link to={`/runs/${entry.run_id}`} onClick={(e) => e.stopPropagation()}>
                                <ShortId id={entry.run_id} />
                              </Link>
                            ) : (
                              <span className="faint">—</span>
                            )}
                          </td>
                          <td className="num muted">
                            {entry.latency_ms === null ? "—" : `${entry.latency_ms}ms`}
                          </td>
                          <td className="num muted">
                            {(entry.tokens_in ?? 0) + (entry.tokens_out ?? 0) || "—"}
                          </td>
                          <td className="num muted">
                            {entry.cost_estimate === null ? "—" : `$${entry.cost_estimate.toFixed(6)}`}
                          </td>
                          <td className="muted">{formatDateTime(entry.created_at)}</td>
                        </tr>
                        {open && (
                          <tr>
                            <td colSpan={8} style={{ height: "auto", padding: "var(--sp-3) var(--sp-4)" }}>
                              <div className="grid grid--2" {...testid(TID.auditJson(entry.id))}>
                                <div>
                                  <div className="metric__label">Payload</div>
                                  <pre className="json">{JSON.stringify(entry.payload, null, 2)}</pre>
                                </div>
                                <div>
                                  <div className="metric__label">Result</div>
                                  <pre className="json">{JSON.stringify(entry.result, null, 2)}</pre>
                                </div>
                              </div>
                            </td>
                          </tr>
                        )}
                      </Fragment>
                    );
                  })}
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
                {...testid(TID.auditPrev)}
              >
                Previous
              </button>
              <button
                type="button"
                className="btn btn--sm"
                disabled={offset + PAGE >= total}
                onClick={() => setOffset(offset + PAGE)}
                {...testid(TID.auditNext)}
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
