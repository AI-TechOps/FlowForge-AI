/**
 * Tickets list + the new-ticket form (spec 07 screens 5 and 6).
 *
 * "Run triage" is operator work, so the button is absent for other roles —
 * presentationally. `POST /api/runs` carries OPERATOR_WORK server-side, which
 * is the control; this only avoids offering an action that would be refused.
 *
 * Starting triage navigates straight to the run, because the interesting part
 * is what the agent does next and a list row cannot show it.
 */

import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { useAgentConfig, useCreateTicket, useStartTriage, useTickets } from "../api/hooks";
import type { Ticket } from "../api/types";
import {
  Empty,
  ErrorState,
  Loading,
  Modal,
  PageHead,
  Panel,
  ShortId,
  TicketBadge,
  timeAgo,
} from "../components/ui";
import { useHasRole, useTitle } from "../shell/Shell";
import { TID, testid } from "../testids";

const STATUSES = ["new", "triaged", "actioned", "closed"];

export function Tickets() {
  useTitle("Tickets");
  const navigate = useNavigate();
  const isOperator = useHasRole("operator", "administrator");

  const [status, setStatus] = useState("");
  const [service, setService] = useState("");
  const [seedOnly, setSeedOnly] = useState("");
  const [composing, setComposing] = useState(false);

  const filters = useMemo(
    () => ({
      status: status || undefined,
      service: service || undefined,
      is_eval_seed: seedOnly === "" ? undefined : seedOnly === "true",
    }),
    [status, service, seedOnly],
  );

  const tickets = useTickets(filters);
  const triage = useStartTriage();

  const startTriage = (ticket: Ticket) => {
    triage.mutate(ticket.id, {
      onSuccess: (run) => navigate(`/runs/${run.id}`),
    });
  };

  return (
    <div {...testid(TID.tickets)}>
      <PageHead
        title="Tickets"
        subtitle="Support issues waiting for triage, and the ones the agent has already handled."
        actions={
          isOperator ? (
            <button
              type="button"
              className="btn btn--primary"
              onClick={() => setComposing(true)}
              {...testid(TID.newTicketOpen)}
            >
              New ticket
            </button>
          ) : undefined
        }
      />

      <Panel
        flush
        title={
          <div className="filters" style={{ flex: 1 }}>
            <select
              className="select"
              value={status}
              onChange={(e) => setStatus(e.target.value)}
              aria-label="Filter by status"
              {...testid(TID.ticketFilterStatus)}
            >
              <option value="">All statuses</option>
              {STATUSES.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
            <input
              className="input"
              placeholder="Service…"
              value={service}
              onChange={(e) => setService(e.target.value)}
              aria-label="Filter by service"
              {...testid(TID.ticketFilterService)}
            />
            <select
              className="select"
              value={seedOnly}
              onChange={(e) => setSeedOnly(e.target.value)}
              aria-label="Filter eval seeds"
              {...testid(TID.ticketFilterSeed)}
            >
              <option value="">All tickets</option>
              <option value="true">Eval seeds only</option>
              <option value="false">Exclude eval seeds</option>
            </select>
            {tickets.data && (
              <span className="faint" style={{ fontSize: "var(--fs-xs)" }}>
                {tickets.data.length} shown
              </span>
            )}
          </div>
        }
      >
        {tickets.isPending && <Loading label="Loading tickets" />}
        {tickets.isError && <ErrorState error={tickets.error} onRetry={() => void tickets.refetch()} />}
        {tickets.data?.length === 0 && (
          <Empty
            title="No tickets match"
            body={
              status || service || seedOnly
                ? "Try clearing the filters above."
                : "File one to watch the agent triage it end to end."
            }
            action={
              isOperator ? (
                <button type="button" className="btn btn--primary" onClick={() => setComposing(true)}>
                  New ticket
                </button>
              ) : undefined
            }
          />
        )}

        {tickets.data && tickets.data.length > 0 && (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Ref</th>
                  <th>Title</th>
                  <th>Status</th>
                  <th>Service</th>
                  <th>Department</th>
                  <th>Team</th>
                  <th>Created</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {tickets.data.map((ticket) => (
                  <tr key={ticket.id} {...testid(TID.ticketRow(ticket.id))}>
                    <td>
                      {ticket.external_ref ? (
                        <span className="mono">{ticket.external_ref}</span>
                      ) : (
                        <ShortId id={ticket.id} />
                      )}
                    </td>
                    <td className="wrap">
                      {ticket.title}
                      {ticket.is_eval_seed && (
                        <span className="badge badge--accent" style={{ marginLeft: "var(--sp-2)" }}>
                          eval seed
                        </span>
                      )}
                    </td>
                    <td>
                      <TicketBadge status={ticket.status} {...testid(TID.ticketStatus(ticket.id))} />
                    </td>
                    <td className="muted">{ticket.service ?? "—"}</td>
                    <td className="muted">{ticket.department ?? "—"}</td>
                    <td className="muted">{ticket.assigned_team ?? "—"}</td>
                    <td className="muted">{timeAgo(ticket.created_at)}</td>
                    <td style={{ textAlign: "right" }}>
                      {isOperator && (
                        <button
                          type="button"
                          className="btn btn--sm"
                          disabled={triage.isPending}
                          onClick={() => startTriage(ticket)}
                          {...testid(TID.ticketTriage(ticket.id))}
                        >
                          {triage.isPending && triage.variables === ticket.id
                            ? "Starting…"
                            : "Run triage"}
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      {triage.isError && (
        <div className="banner banner--err" style={{ marginTop: "var(--sp-4)" }} role="alert">
          {triage.error instanceof Error ? triage.error.message : "Could not start triage"}
        </div>
      )}

      {composing && <NewTicketModal onClose={() => setComposing(false)} />}
    </div>
  );
}

/**
 * The exact MVP form: title, description, requester department, affected
 * service, optional existing priority (spec 07 screen 6).
 *
 * Validation is client-side courtesy only — the API validates independently,
 * and a field that passes here can still be refused there.
 */
function NewTicketModal({ onClose }: { onClose: () => void }) {
  const navigate = useNavigate();
  const create = useCreateTicket();
  const config = useAgentConfig();

  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [department, setDepartment] = useState("");
  const [service, setService] = useState("");
  const [priority, setPriority] = useState("");
  const [touched, setTouched] = useState(false);

  const titleError = touched && title.trim().length < 4 ? "At least 4 characters." : null;
  const descError =
    touched && description.trim().length < 10
      ? "Give the agent something to work with — at least 10 characters."
      : null;
  const valid = title.trim().length >= 4 && description.trim().length >= 10;

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    setTouched(true);
    if (!valid) return;
    create.mutate(
      {
        title: title.trim(),
        description: description.trim(),
        department: department.trim() || undefined,
        service: service.trim() || undefined,
        priority: priority || undefined,
      },
      {
        onSuccess: (ticket) => {
          onClose();
          // Straight to triage-able state: the list refreshes via the mutation's
          // invalidation, and the new ticket is the reason the user came here.
          navigate(`/tickets?created=${ticket.id}`);
        },
      },
    );
  };

  return (
    <Modal
      title="New ticket"
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button
            type="submit"
            form="new-ticket"
            className="btn btn--primary"
            disabled={create.isPending}
            {...testid(TID.newTicketSubmit)}
          >
            {create.isPending ? "Creating…" : "Create ticket"}
          </button>
        </>
      }
    >
      <form id="new-ticket" onSubmit={submit} {...testid(TID.newTicketForm)}>
        <div className="form-grid">
          <div className="field form-grid--full">
            <label className="field__label" htmlFor="t-title">
              Title
            </label>
            <input
              id="t-title"
              className="input"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Cannot connect to VPN from home"
              aria-invalid={titleError ? "true" : undefined}
              {...testid(TID.newTicketTitle)}
            />
            {titleError && <span className="field__error">{titleError}</span>}
          </div>

          <div className="field form-grid--full">
            <label className="field__label" htmlFor="t-desc">
              Description
            </label>
            <textarea
              id="t-desc"
              className="textarea"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="What the requester reported, in their words."
              aria-invalid={descError ? "true" : undefined}
              {...testid(TID.newTicketDescription)}
            />
            {descError ? (
              <span className="field__error">{descError}</span>
            ) : (
              <span className="field__hint">
                This is what retrieval searches against — detail improves grounding.
              </span>
            )}
          </div>

          <div className="field">
            <label className="field__label" htmlFor="t-dept">
              Requester department
            </label>
            <input
              id="t-dept"
              className="input"
              value={department}
              onChange={(e) => setDepartment(e.target.value)}
              placeholder="Finance"
              {...testid(TID.newTicketDepartment)}
            />
            <span className="field__hint">Where the requester sits, not who will fix it.</span>
          </div>

          <div className="field">
            <label className="field__label" htmlFor="t-service">
              Affected service
            </label>
            <input
              id="t-service"
              className="input"
              value={service}
              onChange={(e) => setService(e.target.value)}
              placeholder="MeridianConnect VPN"
              {...testid(TID.newTicketService)}
            />
          </div>

          <div className="field">
            <label className="field__label" htmlFor="t-priority">
              Existing priority <span className="faint">(optional)</span>
            </label>
            <select
              id="t-priority"
              className="select"
              value={priority}
              onChange={(e) => setPriority(e.target.value)}
              {...testid(TID.newTicketPriority)}
            >
              <option value="">Not set</option>
              {(config.data?.taxonomy.priorities ?? []).map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
            <span className="field__hint">The agent may propose a change to this.</span>
          </div>
        </div>

        {create.isError && (
          <div className="banner banner--err" style={{ marginTop: "var(--sp-4)" }} role="alert">
            {create.error instanceof Error ? create.error.message : "Could not create the ticket"}
          </div>
        )}
      </form>
    </Modal>
  );
}
