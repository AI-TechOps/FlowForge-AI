/**
 * ⌘K command palette.
 *
 * Navigation plus live search over tickets and runs, from the keyboard. It
 * respects roles the same way the sidebar does — presentationally — so an
 * operator cannot jump to the audit log from here either, and the server would
 * refuse them anyway.
 *
 * Search is client-side over data the app has already fetched. That is a
 * deliberate limit rather than an oversight: there is no search endpoint, and
 * inventing one from the frontend by paging the whole ticket table would be
 * slower and less honest than saying "recent" and meaning it.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { useRuns, useTickets } from "../api/hooks";
import type { Role } from "../api/types";
import { Icon } from "./ui";
import { NAV, canSee } from "../shell/Shell";
import { TID, testid } from "../testids";

interface Command {
  id: string;
  label: string;
  hint?: string;
  group: string;
  icon: JSX.Element;
  run: () => void;
}

export function CommandPalette({
  open,
  onClose,
  roles,
  onToggleTheme,
}: {
  open: boolean;
  onClose: () => void;
  roles: Role[];
  onToggleTheme: () => void;
}) {
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  // Gated on `open`, and the gating is the point: these hooks used to run
  // unconditionally under a comment claiming they did not. That cost every
  // page load two queries for a feature nobody had opened, and — worse — the
  // palette's unfiltered ticket query shares a cache key with the Tickets
  // screen's, so the screen inherited whatever the palette had fetched at
  // login and rendered a stale status until it revalidated.
  const tickets = useTickets({}, open);
  const runs = useRuns({ limit: 25 }, open);

  useEffect(() => {
    if (open) {
      setQuery("");
      setActive(0);
      // rAF, not a bare focus(): the input does not exist until this paints.
      requestAnimationFrame(() => inputRef.current?.focus());
    }
  }, [open]);

  const commands = useMemo<Command[]>(() => {
    const list: Command[] = [];

    for (const item of NAV.filter((i) => canSee(i, roles))) {
      list.push({
        id: `nav-${item.route}`,
        label: item.label,
        group: "Go to",
        icon: item.icon({ size: 15 }),
        run: () => navigate(`/${item.route}`),
      });
    }

    list.push({
      id: "theme",
      label: "Toggle theme",
      hint: "dark / light",
      group: "Actions",
      icon: Icon.sun({ size: 15 }),
      run: onToggleTheme,
    });

    const q = query.trim().toLowerCase();
    if (q.length >= 2) {
      for (const t of (tickets.data ?? []).slice(0, 60)) {
        if (!t.title.toLowerCase().includes(q) && !(t.external_ref ?? "").toLowerCase().includes(q))
          continue;
        list.push({
          id: `ticket-${t.id}`,
          label: t.title,
          hint: t.external_ref ?? t.status,
          group: "Tickets",
          icon: Icon.ticket({ size: 15 }),
          run: () => navigate("/tickets"),
        });
      }
      for (const r of runs.data?.runs ?? []) {
        if (!r.id.toLowerCase().startsWith(q)) continue;
        list.push({
          id: `run-${r.id}`,
          label: `Run ${r.id.slice(0, 8)}`,
          hint: r.status.replace(/_/g, " "),
          group: "Runs",
          icon: Icon.run({ size: 15 }),
          run: () => navigate(`/runs/${r.id}`),
        });
      }
    }

    return list;
  }, [roles, query, tickets.data, runs.data, navigate, onToggleTheme]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return commands;
    return commands.filter(
      (c) => c.label.toLowerCase().includes(q) || (c.hint ?? "").toLowerCase().includes(q),
    );
  }, [commands, query]);

  useEffect(() => setActive(0), [query]);

  if (!open) return null;

  const choose = (cmd: Command) => {
    cmd.run();
    onClose();
  };

  const onKeyDown = (event: React.KeyboardEvent) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActive((a) => Math.min(a + 1, filtered.length - 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActive((a) => Math.max(a - 1, 0));
    } else if (event.key === "Enter") {
      event.preventDefault();
      const cmd = filtered[active];
      if (cmd) choose(cmd);
    } else if (event.key === "Escape") {
      onClose();
    }
  };

  let lastGroup = "";

  return (
    <div className="palette-backdrop" role="presentation" onClick={onClose}>
      <div
        className="palette"
        role="dialog"
        aria-modal="true"
        aria-label="Command palette"
        onClick={(e) => e.stopPropagation()}
        {...testid(TID.palette)}
      >
        <div className="palette__search">
          {Icon.search({ size: 16 })}
          <input
            ref={inputRef}
            className="palette__input"
            placeholder="Search tickets, runs, or jump to a screen…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={onKeyDown}
            {...testid(TID.paletteInput)}
          />
          <kbd className="kbd">esc</kbd>
        </div>

        <div className="palette__list" role="listbox">
          {filtered.length === 0 && (
            <div className="palette__empty">
              No matches for <strong>{query}</strong>
            </div>
          )}
          {filtered.map((cmd, i) => {
            const heading = cmd.group !== lastGroup ? cmd.group : null;
            lastGroup = cmd.group;
            return (
              <div key={cmd.id}>
                {heading && <div className="palette__group">{heading}</div>}
                <button
                  type="button"
                  role="option"
                  aria-selected={i === active}
                  className={i === active ? "palette__item palette__item--active" : "palette__item"}
                  onMouseEnter={() => setActive(i)}
                  onClick={() => choose(cmd)}
                  {...testid(TID.paletteItem(cmd.id))}
                >
                  <span className="palette__icon">{cmd.icon}</span>
                  <span className="palette__label truncate">{cmd.label}</span>
                  {cmd.hint && <span className="palette__hint truncate">{cmd.hint}</span>}
                </button>
              </div>
            );
          })}
        </div>

        <div className="palette__foot">
          <span>
            <kbd className="kbd">↑</kbd>
            <kbd className="kbd">↓</kbd> navigate
          </span>
          <span>
            <kbd className="kbd">↵</kbd> select
          </span>
          <span className="pagination__spacer" />
          <span className="faint">Search covers loaded tickets and recent runs</span>
        </div>
      </div>
    </div>
  );
}

/** Binds ⌘K / Ctrl-K globally. */
export function useCommandPalette() {
  const [open, setOpen] = useState(false);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setOpen((o) => !o);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  return { open, setOpen };
}
