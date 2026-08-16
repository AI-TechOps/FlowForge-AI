/**
 * Read-only agent configuration (D21 decision 5).
 *
 * CLAUDE.md is explicit: agent configuration lives in code and database
 * records, and "a read-only config page is sufficient". So this shows what is
 * running and offers no way to change it — changing it is a commit, which is
 * the property that makes an agent's behaviour reviewable.
 *
 * The taxonomy comes from the same source the validator uses, so a config page
 * cannot show categories the agent would actually reject.
 */

import { useAgentConfig } from "../api/hooks";
import { ErrorState, Loading, Mono, PageHead, Panel } from "../components/ui";
import { useTitle } from "../shell/Shell";
import { TID, testid } from "../testids";

function Row({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <>
      <dt>{label}</dt>
      <dd {...testid(TID.configField(label.toLowerCase().replace(/\s+/g, "_")))}>
        <Mono>{value}</Mono>
        {hint && (
          <div className="faint" style={{ fontSize: "var(--fs-xs)", marginTop: 2 }}>
            {hint}
          </div>
        )}
      </dd>
    </>
  );
}

export function AgentConfig() {
  useTitle("Agent config");
  const config = useAgentConfig();

  if (config.isPending) return <Loading label="Loading configuration" />;
  if (config.isError)
    return <ErrorState error={config.error} onRetry={() => void config.refetch()} />;
  if (!config.data) return null;

  const c = config.data;
  const groups: [string, string[]][] = [
    ["categories", c.taxonomy.categories],
    ["urgencies", c.taxonomy.urgencies],
    ["teams", c.taxonomy.teams],
    ["priorities", c.taxonomy.priorities],
  ];

  return (
    <div {...testid(TID.agentConfig)}>
      <PageHead
        eyebrow="Configuration lives in code"
        title="Agent configuration"
        subtitle="What is running right now. Read-only by design — agent configuration lives in code and database records, so changing it is a commit."
      />

      <div className="stack">
        <div className="grid grid--2">
          <Panel title="Versions and models">
            <dl className="dl">
              <Row label="Agent version" value={c.agent_version} hint="Bumps whenever prompt text changes" />
              <Row label="Judge version" value={c.judge_version} />
              <Row label="Provider" value={c.llm_provider} />
              <Row label="Triage model" value={c.triage_model} />
              <Row
                label="Judge model"
                value={c.judge_model}
                hint="Must be a different family from triage — the stack refuses to start otherwise"
              />
              <Row label="Embedding model" value={c.embedding_model} />
            </dl>
          </Panel>

          <Panel title="Execution limits">
            <dl className="dl">
              <Row label="Run timeout" value={`${c.run_timeout_seconds}s`} hint="After this a run is considered stale and may be reclaimed" />
              <Row label="Max attempts" value={String(c.max_run_attempts)} hint="Then the run dead-letters rather than retrying forever" />
            </dl>
            <div className="banner banner--info" style={{ marginTop: "var(--sp-4)" }}>
              The five tools are fixed in code: <Mono>search_company_knowledge</Mono> and{" "}
              <Mono>get_ticket</Mono> auto-execute; <Mono>assign_ticket</Mono>,{" "}
              <Mono>change_ticket_priority</Mono> and <Mono>add_internal_note</Mono> require
              approval.
            </div>
          </Panel>
        </div>

        <Panel title="Taxonomy">
          <p className="muted" style={{ marginBottom: "var(--sp-4)" }}>
            The only values structured output may contain. Anything else is a schema violation and
            the run retries once, then fails closed.
          </p>
          <div className="grid grid--2">
            {groups.map(([name, values]) => (
              <div key={name} {...testid(TID.taxonomyGroup(name))}>
                <div className="metric__label">{name}</div>
                <div
                  style={{
                    display: "flex",
                    flexWrap: "wrap",
                    gap: "var(--sp-2)",
                    marginTop: "var(--sp-2)",
                  }}
                >
                  {values.map((value) => (
                    <span key={value} className="badge">
                      <Mono>{value}</Mono>
                    </span>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </Panel>
      </div>
    </div>
  );
}
