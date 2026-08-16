/**
 * Theme defaulting. Small, but it is the thing that decides what every
 * screenshot and every browser gate sees before anyone touches a toggle.
 */

import { describe, expect, it } from "vitest";

import { activeTheme, applyStoredTheme, applyTheme, setTheme, storedTheme } from "./theme";

describe("theme", () => {
  it("defaults to dark with nothing stored", () => {
    expect(storedTheme()).toBeNull();
    expect(activeTheme()).toBe("dark");
  });

  it("ignores the OS preference entirely", () => {
    // A browser reporting light must not move us: "dark by default" quietly
    // became "whatever the OS says", which made a demo recorded on a
    // light-mode machine come out light and made every browser gate inherit
    // the CI runner's colour scheme.
    window.matchMedia = ((query: string) => ({
      matches: true,
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    })) as typeof window.matchMedia;

    expect(activeTheme()).toBe("dark");
  });

  it("honours and persists an explicit choice", () => {
    setTheme("light");
    expect(storedTheme()).toBe("light");
    expect(activeTheme()).toBe("light");
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");

    setTheme("dark");
    expect(activeTheme()).toBe("dark");
    // Dark is the absence of the attribute, so the default path needs no
    // selector at all.
    expect(document.documentElement.getAttribute("data-theme")).toBeNull();
  });

  it("ignores a corrupt stored value instead of applying it", () => {
    localStorage.setItem("flowforge.theme", "chartreuse");
    expect(storedTheme()).toBeNull();
    expect(activeTheme()).toBe("dark");
  });

  it("applies the stored theme on boot", () => {
    localStorage.setItem("flowforge.theme", "light");
    applyStoredTheme();
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
    applyTheme("dark");
    expect(document.documentElement.getAttribute("data-theme")).toBeNull();
  });
});
