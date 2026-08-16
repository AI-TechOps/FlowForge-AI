/**
 * Theme selection (D21 decision 8).
 *
 * Dark is the default and is what `:root` already declares, so the correct
 * theme is painted before React mounts — there is no flash of the wrong one.
 * Only an explicit choice moves it, and that choice persists.
 *
 * **`prefers-color-scheme` is deliberately not consulted.** It was, and it was
 * wrong twice over: "dark by default" quietly became "whatever the OS says",
 * so a demo recorded on a light-mode machine came out light; and every
 * browser-driven gate inherited the CI runner's colour scheme, which makes
 * theme assertions flake for a reason nobody would think to look for. A single
 * deterministic default plus a persisted toggle is both what the decision said
 * and the only version that is testable.
 *
 * `applyStoredTheme()` is called from an inline script in index.html rather
 * than from a component, because by the time a component renders the user has
 * already seen a frame.
 */

const KEY = "flowforge.theme";

export type Theme = "dark" | "light";

export function storedTheme(): Theme | null {
  try {
    const value = localStorage.getItem(KEY);
    return value === "dark" || value === "light" ? value : null;
  } catch {
    // Private mode with storage disabled: dark is a fine answer.
    return null;
  }
}

export function activeTheme(): Theme {
  return storedTheme() ?? "dark";
}

export function applyTheme(theme: Theme): void {
  // Dark is the default in tokens.css, so it is expressed as the *absence* of
  // the attribute. That keeps the default path free of a selector.
  if (theme === "light") {
    document.documentElement.setAttribute("data-theme", "light");
  } else {
    document.documentElement.removeAttribute("data-theme");
  }
}

export function setTheme(theme: Theme): void {
  try {
    localStorage.setItem(KEY, theme);
  } catch {
    // Storage refused; the theme still applies for this session.
  }
  applyTheme(theme);
}

export function applyStoredTheme(): void {
  applyTheme(activeTheme());
}
