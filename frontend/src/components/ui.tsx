/**
 * Shared primitives. Presentational only — nothing here fetches, decides
 * permissions, or knows about a route.
 *
 * The three state components exist because spec 07 requires loading, empty and
 * error on every data view, and "no blank screens" is only true if the boring
 * case is as easy to render as the happy one.
 */

import type { ReactNode } from "react";

import { TID, testid } from "../testids";
import type { DocumentStatus, RunStatus, TicketStatus } from "../api/types";

/* ====================================================================== */
/* Icons — inline SVG, 16px grid, currentColor                             */
/* ====================================================================== */

type IconProps = { size?: number; className?: string };

const svg = (path: ReactNode, { size = 16, className }: IconProps) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 16 16"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.5"
    strokeLinecap="round"
    strokeLinejoin="round"
    className={className}
    aria-hidden="true"
  >
    {path}
  </svg>
);

export const Icon = {
  dashboard: (p: IconProps = {}) =>
    svg(
      <>
        <rect x="2" y="2" width="5" height="5" rx="1" />
        <rect x="9" y="2" width="5" height="5" rx="1" />
        <rect x="2" y="9" width="5" height="5" rx="1" />
        <rect x="9" y="9" width="5" height="5" rx="1" />
      </>,
      p,
    ),
  ticket: (p: IconProps = {}) =>
    svg(
      <>
        <path d="M2 5.5a1.5 1.5 0 0 1 1.5-1.5h9A1.5 1.5 0 0 1 14 5.5v1a1.5 1.5 0 0 0 0 3v1a1.5 1.5 0 0 1-1.5 1.5h-9A1.5 1.5 0 0 1 2 10.5v-1a1.5 1.5 0 0 0 0-3v-1Z" />
        <path d="M9.5 4v8" strokeDasharray="1.5 1.5" />
      </>,
      p,
    ),
  run: (p: IconProps = {}) =>
    svg(
      <>
        <circle cx="8" cy="8" r="6" />
        <path d="M8 4.5V8l2.5 1.5" />
      </>,
      p,
    ),
  approval: (p: IconProps = {}) =>
    svg(
      <>
        <path d="M8 1.5 13.5 4v4c0 3-2.3 5.6-5.5 6.5C4.8 13.6 2.5 11 2.5 8V4L8 1.5Z" />
        <path d="M5.75 8 7.3 9.5l3-3.25" />
      </>,
      p,
    ),
  document: (p: IconProps = {}) =>
    svg(
      <>
        <path d="M9 1.5H4.5A1.5 1.5 0 0 0 3 3v10a1.5 1.5 0 0 0 1.5 1.5h7A1.5 1.5 0 0 0 13 13V5.5L9 1.5Z" />
        <path d="M9 1.5v4h4" />
      </>,
      p,
    ),
  evaluation: (p: IconProps = {}) =>
    svg(
      <>
        <path d="M2 13.5h12" />
        <path d="M4 13.5v-5M7.33 13.5v-8M10.67 13.5v-3M14 13.5v-10" />
      </>,
      p,
    ),
  audit: (p: IconProps = {}) =>
    svg(
      <>
        <path d="M3 2.5h10v11H3z" />
        <path d="M5.5 5.5h5M5.5 8h5M5.5 10.5h3" />
      </>,
      p,
    ),
  config: (p: IconProps = {}) =>
    svg(
      <>
        <circle cx="8" cy="8" r="2" />
        <path d="M8 1.5v1.75M8 12.75v1.75M14.5 8h-1.75M3.25 8H1.5M12.6 3.4l-1.24 1.24M4.64 11.36 3.4 12.6M12.6 12.6l-1.24-1.24M4.64 4.64 3.4 3.4" />
      </>,
      p,
    ),
  sun: (p: IconProps = {}) =>
    svg(
      <>
        <circle cx="8" cy="8" r="3" />
        <path d="M8 1v1.5M8 13.5V15M15 8h-1.5M2.5 8H1M12.95 3.05l-1.06 1.06M4.11 11.89l-1.06 1.06M12.95 12.95l-1.06-1.06M4.11 4.11 3.05 3.05" />
      </>,
      p,
    ),
  moon: (p: IconProps = {}) => svg(<path d="M13.5 9.3A5.8 5.8 0 0 1 6.7 2.5a5.8 5.8 0 1 0 6.8 6.8Z" />, p),
  inbox: (p: IconProps = {}) =>
    svg(
      <>
        <path d="M2 9.5 3.8 3.2A1.5 1.5 0 0 1 5.25 2h5.5a1.5 1.5 0 0 1 1.45 1.2L14 9.5v3A1.5 1.5 0 0 1 12.5 14h-9A1.5 1.5 0 0 1 2 12.5v-3Z" />
        <path d="M2 9.5h3l1 2h4l1-2h3" />
      </>,
      p,
    ),
  alert: (p: IconProps = {}) =>
    svg(
      <>
        <circle cx="8" cy="8" r="6.25" />
        <path d="M8 5v3.5M8 10.75v.5" />
      </>,
      p,
    ),
  chevron: (p: IconProps = {}) => svg(<path d="M6 4l4 4-4 4" />, p),
  external: (p: IconProps = {}) =>
    svg(
      <>
        <path d="M9 2.5h4.5V7" />
        <path d="M13.5 2.5 7 9" />
        <path d="M12 9.5v3A1.5 1.5 0 0 1 10.5 14h-7A1.5 1.5 0 0 1 2 12.5v-7A1.5 1.5 0 0 1 3.5 4h3" />
      </>,
      p,
    ),
  upload: (p: IconProps = {}) =>
    svg(
      <>
        <path d="M8 10.5V2.5M5 5.5 8 2.5l3 3" />
        <path d="M2.5 10.5v2A1.5 1.5 0 0 0 4 14h8a1.5 1.5 0 0 0 1.5-1.5v-2" />
      </>,
      p,
    ),
};

/* ====================================================================== */
/* Status badges                                                           */
/* ====================================================================== */

type Tone = "ok" | "warn" | "err" | "info" | "accent" | "neutral";

const RUN_TONE: Record<RunStatus, Tone> = {
  queued: "neutral",
  running: "info",
  awaiting_approval: "warn",
  executing: "info",
  completed: "ok",
  rejected: "neutral",
  failed: "err",
};

const TICKET_TONE: Record<TicketStatus, Tone> = {
  new: "neutral",
  triaged: "info",
  actioned: "ok",
  closed: "neutral",
};

const DOC_TONE: Record<DocumentStatus, Tone> = {
  pending: "neutral",
  processing: "info",
  ready: "ok",
  failed: "err",
};

export function Badge({
  tone = "neutral",
  live = false,
  children,
  ...rest
}: {
  tone?: Tone;
  live?: boolean;
  children: ReactNode;
} & Record<string, unknown>) {
  const cls = tone === "neutral" ? "badge" : `badge badge--${tone}`;
  return (
    <span className={cls} {...rest}>
      <span className={live ? "badge__dot badge__dot--live" : "badge__dot"} />
      {children}
    </span>
  );
}

export const RunBadge = ({ status, ...rest }: { status: RunStatus } & Record<string, unknown>) => (
  <Badge
    tone={RUN_TONE[status] ?? "neutral"}
    live={status === "running" || status === "executing" || status === "queued"}
    {...rest}
  >
    {status.replace(/_/g, " ")}
  </Badge>
);

export const TicketBadge = ({ status, ...rest }: { status: TicketStatus } & Record<string, unknown>) => (
  <Badge tone={TICKET_TONE[status] ?? "neutral"} {...rest}>
    {status}
  </Badge>
);

export const DocBadge = ({ status, ...rest }: { status: DocumentStatus } & Record<string, unknown>) => (
  <Badge
    tone={DOC_TONE[status] ?? "neutral"}
    live={status === "processing" || status === "pending"}
    {...rest}
  >
    {status}
  </Badge>
);

/* ====================================================================== */
/* Loading / empty / error                                                 */
/* ====================================================================== */

export function Loading({ label = "Loading…", rows = 5 }: { label?: string; rows?: number }) {
  return (
    <div {...testid(TID.loading)} aria-busy="true" aria-live="polite" style={{ padding: "var(--sp-4)" }}>
      <span className="sr-only">{label}</span>
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="skeleton skeleton--row" style={{ width: `${92 - i * 9}%` }} />
      ))}
    </div>
  );
}

export function Empty({ title, body, action }: { title: string; body?: string; action?: ReactNode }) {
  return (
    <div className="state" {...testid(TID.empty)}>
      <span className="state__icon">{Icon.inbox({ size: 32 })}</span>
      <div className="state__title">{title}</div>
      {body && <p className="state__body">{body}</p>}
      {action}
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const message = error instanceof Error ? error.message : String(error);
  return (
    <div className="state state--error" {...testid(TID.error)} role="alert">
      <span className="state__icon">{Icon.alert({ size: 32 })}</span>
      <div className="state__title">Something went wrong</div>
      <p className="state__body" {...testid(TID.errorDetail)}>
        {message}
      </p>
      {onRetry && (
        <button type="button" className="btn" onClick={onRetry} {...testid(TID.retry)}>
          Try again
        </button>
      )}
    </div>
  );
}

/* ====================================================================== */
/* Small helpers                                                           */
/* ====================================================================== */

export const Mono = ({ children, title }: { children: ReactNode; title?: string }) => (
  <span className="mono" title={title}>
    {children}
  </span>
);

/** Short form of a uuid — full value stays in the title attribute. */
export const ShortId = ({ id }: { id: string }) => (
  <span className="mono" title={id}>
    {id.slice(0, 8)}
  </span>
);

export function PageHead({
  title,
  subtitle,
  actions,
}: {
  title: string;
  subtitle?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <header className="page-head">
      <div className="page-head__text">
        <h1>{title}</h1>
        {subtitle && <p>{subtitle}</p>}
      </div>
      {actions && <div className="page-head__actions">{actions}</div>}
    </header>
  );
}

export function Panel({
  title,
  actions,
  flush = false,
  children,
  ...rest
}: {
  title?: ReactNode;
  actions?: ReactNode;
  flush?: boolean;
  children: ReactNode;
} & Record<string, unknown>) {
  return (
    <section className="panel" {...rest}>
      {title && (
        <div className="panel__head">
          {title}
          {actions && <div className="panel__head-actions">{actions}</div>}
        </div>
      )}
      <div className={flush ? "panel__body panel__body--flush" : "panel__body"}>{children}</div>
    </section>
  );
}

/** Renders `—` for null/undefined so an absent value never looks like a bug. */
export const Maybe = ({ value }: { value: unknown }) =>
  value === null || value === undefined || value === "" ? (
    <span className="faint">—</span>
  ) : (
    <>{String(value)}</>
  );

export const pct = (value: number | null | undefined, digits = 1): string =>
  value === null || value === undefined ? "—" : `${(value * 100).toFixed(digits)}%`;

export const num = (value: number | null | undefined, digits = 0): string =>
  value === null || value === undefined ? "—" : value.toFixed(digits);

export function timeAgo(iso: string | null | undefined): string {
  if (!iso) return "—";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "—";
  const secs = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (secs < 60) return `${secs}s ago`;
  if (secs < 3600) return `${Math.round(secs / 60)}m ago`;
  if (secs < 86400) return `${Math.round(secs / 3600)}h ago`;
  return `${Math.round(secs / 86400)}d ago`;
}

export const formatDateTime = (iso: string | null | undefined): string =>
  iso ? new Date(iso).toLocaleString() : "—";

export function Modal({
  title,
  onClose,
  children,
  footer,
  ...rest
}: {
  title: ReactNode;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
} & Record<string, unknown>) {
  return (
    <div
      className="modal-backdrop"
      role="presentation"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="modal" role="dialog" aria-modal="true" aria-label={String(title)} {...rest}>
        <div className="modal__head">
          {title}
          <button
            type="button"
            className="btn btn--ghost btn--icon"
            style={{ marginLeft: "auto" }}
            onClick={onClose}
            aria-label="Close"
          >
            ✕
          </button>
        </div>
        <div className="modal__body">{children}</div>
        {footer && <div className="modal__foot">{footer}</div>}
      </div>
    </div>
  );
}
