/**
 * The app shell: sidebar, top bar, and the guard that decides what a role may
 * reach.
 *
 * **Role gating here is presentational, never protective** (spec 07). The
 * sidebar hides what you cannot use and a guarded route refuses politely, but
 * the server is the only real enforcer — every one of these endpoints carries
 * its own role dependency, and a user who edits the URL still gets a 403 from
 * the API. Hiding a link is a courtesy, not a control.
 */

import { useEffect, useState } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";

import { useApprovals, useHealth } from "../api/hooks";
import { CommandPalette, useCommandPalette } from "../components/CommandPalette";
import type { Identity, Role } from "../api/types";
import { Icon } from "../components/ui";
import { clearToken, storedToken } from "../auth";
import { TID, testid } from "../testids";
import { activeTheme, setTheme, type Theme } from "../theme";

export interface NavItem {
  route: string;
  label: string;
  icon: (p?: { size?: number }) => JSX.Element;
  /** Roles that may see this link. Empty means everyone signed in. */
  roles: Role[];
  section?: string;
}

/**
 * The nav, mirroring each endpoint's server-side role dependency. These lists
 * are copied deliberately rather than derived: if the two drift, the server
 * wins and the user sees a refusal instead of a broken screen.
 */
export const NAV: NavItem[] = [
  { route: "", label: "Dashboard", icon: Icon.dashboard, roles: [] },
  { route: "tickets", label: "Tickets", icon: Icon.ticket, roles: [] },
  { route: "runs", label: "Runs", icon: Icon.run, roles: [] },
  {
    route: "approvals",
    label: "Approvals",
    icon: Icon.approval,
    roles: ["approver", "administrator"],
  },
  {
    route: "documents",
    label: "Knowledge",
    icon: Icon.document,
    roles: ["administrator"],
    section: "Administration",
  },
  { route: "evaluation", label: "Evaluation", icon: Icon.evaluation, roles: ["administrator"] },
  { route: "audit", label: "Audit log", icon: Icon.audit, roles: ["administrator"] },
  { route: "config", label: "Agent config", icon: Icon.config, roles: [] },
];

export const canSee = (item: NavItem, roles: Role[]): boolean =>
  item.roles.length === 0 || item.roles.some((r) => roles.includes(r));

export function Shell({ identity }: { identity: Identity }) {
  const navigate = useNavigate();
  const [theme, setThemeState] = useState<Theme>(() => activeTheme());
  const health = useHealth();
  const palette = useCommandPalette();
  const isMac = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform);

  const isApprover = identity.roles.includes("approver") || identity.roles.includes("administrator");
  // Only fetched for roles that may read it — an operator polling a 403 every
  // five seconds is noise in the audit trail and in the console.
  const approvals = useApprovals(isApprover);
  const pending = approvals.data?.filter((a) => a.status === "pending").length ?? 0;

  const toggleTheme = () => {
    const next: Theme = theme === "dark" ? "light" : "dark";
    setTheme(next);
    setThemeState(next);
  };

  const signOut = async () => {
    const token = storedToken();
    if (token) {
      // Best-effort: we issue no token of our own, so the meaningful part is
      // dropping it locally.
      await fetch("/api/logout", {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
      }).catch(() => undefined);
    }
    clearToken();
    navigate("/login", { replace: true });
    window.location.reload();
  };

  const visible = NAV.filter((item) => canSee(item, identity.roles));
  let lastSection: string | undefined;

  return (
    <div className="app" {...testid(TID.app)}>
      <aside className="sidebar" {...testid(TID.sidebar)}>
        <div className="sidebar__brand">
          <span className="sidebar__mark">FF</span>
          FlowForge
        </div>

        <nav>
          {visible.map((item) => {
            const heading = item.section && item.section !== lastSection ? item.section : null;
            lastSection = item.section ?? lastSection;
            return (
              <div key={item.route || "dashboard"}>
                {heading && <div className="sidebar__section">{heading}</div>}
                <NavLink
                  to={`/${item.route}`}
                  end={item.route === ""}
                  className={({ isActive }) => (isActive ? "navlink navlink--active" : "navlink")}
                  {...testid(TID.navLink(item.route || "dashboard"))}
                >
                  <span className="navlink__icon">{item.icon({ size: 16 })}</span>
                  {item.label}
                  {item.route === "approvals" && pending > 0 && (
                    <span className="navlink__count" {...testid(TID.navApprovalCount)}>
                      {pending}
                    </span>
                  )}
                </NavLink>
              </div>
            );
          })}
        </nav>

        <div className="sidebar__footer">
          <div className="user-chip">
            <span className="avatar">{identity.email.slice(0, 2)}</span>
            <div style={{ minWidth: 0 }}>
              <div className="truncate" style={{ fontWeight: 500 }} {...testid(TID.userEmail)}>
                {identity.email}
              </div>
              <div
                className="faint truncate"
                style={{ fontSize: "var(--fs-xs)" }}
                {...testid(TID.userRoles)}
              >
                {identity.roles.join(" · ") || "no roles"}
              </div>
            </div>
          </div>
          <button
            type="button"
            className="btn btn--ghost btn--sm"
            style={{ justifyContent: "flex-start" }}
            onClick={() => void signOut()}
            {...testid(TID.signOut)}
          >
            Sign out
          </button>
        </div>
      </aside>

      <div className="main">
        <div className="topbar">
          <button
            type="button"
            className="searchbtn"
            onClick={() => palette.setOpen(true)}
            {...testid(TID.paletteOpen)}
          >
            {Icon.search({ size: 14 })}
            Search or jump to…
            <span className="searchbtn__hint">
              <kbd className="kbd">{isMac ? "⌘" : "ctrl"}</kbd>
              <kbd className="kbd">K</kbd>
            </span>
          </button>

          <span className="topbar__spacer" />

          <span
            className="row"
            style={{ gap: "var(--sp-2)" }}
            title={
              health.data
                ? `backend ${health.data.status} · db ${health.data.db} · redis ${health.data.redis}`
                : "backend unreachable"
            }
          >
            <span
              {...testid(TID.healthDot)}
              className={health.data?.status === "ok" ? "badge__dot badge__dot--live" : "badge__dot"}
              style={{
                color: health.data?.status === "ok" ? "var(--ok)" : "var(--err)",
              }}
            />
            <span className="faint" style={{ fontSize: "var(--fs-xs)" }}>
              {health.data?.status === "ok" ? "All systems operational" : "Backend unreachable"}
            </span>
          </span>

          <span className="mono faint" style={{ fontSize: "var(--fs-xs)" }} title="Organization">
            org {identity.org_id.slice(0, 8)}
          </span>

          <button
            type="button"
            className="btn btn--ghost btn--sm btn--icon"
            onClick={toggleTheme}
            {...testid(TID.themeToggle)}
            aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}
            title={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}
          >
            {theme === "dark" ? Icon.sun({ size: 14 }) : Icon.moon({ size: 14 })}
          </button>
        </div>

        <main className="content">
          <Outlet />
        </main>
      </div>

      <CommandPalette
        open={palette.open}
        onClose={() => palette.setOpen(false)}
        roles={identity.roles}
        onToggleTheme={toggleTheme}
      />
    </div>
  );
}

/**
 * Renders a refusal rather than a redirect. A redirect would make a
 * mis-remembered bookmark look like a bug ("it keeps sending me to the
 * dashboard"); saying which roles are required is both honest and debuggable.
 */
export function RequireRole({ roles, children }: { roles: Role[]; children: JSX.Element }) {
  const identity = useIdentityContext();
  const allowed = roles.length === 0 || roles.some((r) => identity.roles.includes(r));
  if (allowed) return children;
  return (
    <div className="state" {...testid(TID.forbidden)}>
      <span className="state__icon">{Icon.alert({ size: 32 })}</span>
      <div className="state__title">Not available for your role</div>
      <p className="state__body">
        This screen needs {roles.join(" or ")}. You are signed in as{" "}
        <strong>{identity.email}</strong> with {identity.roles.join(", ") || "no roles"}. The
        server enforces this independently — this message only saves you the request.
      </p>
    </div>
  );
}

/* A deliberately tiny context: the shell always has an identity by the time it
   renders, so screens can read it without prop-drilling or a null check. */
import { createContext, useContext } from "react";

const IdentityContext = createContext<Identity | null>(null);

export const IdentityProvider = IdentityContext.Provider;

export function useIdentityContext(): Identity {
  const value = useContext(IdentityContext);
  if (!value) throw new Error("useIdentityContext used outside the authenticated shell");
  return value;
}

/** True when the signed-in user holds any of the given roles. */
export function useHasRole(...roles: Role[]): boolean {
  const identity = useIdentityContext();
  return roles.some((r) => identity.roles.includes(r));
}

/** Keeps the document title in step with the route. */
export function useTitle(title: string): void {
  useEffect(() => {
    document.title = `${title} · FlowForge`;
    return () => {
      document.title = "FlowForge";
    };
  }, [title]);
}
