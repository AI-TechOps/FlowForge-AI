/**
 * The API client's three invariants, each of which is a bug the day a screen
 * has to remember it on its own.
 */

import { describe, expect, it, vi } from "vitest";

import { ApiError, Unauthenticated, api, withQuery } from "./client";

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

describe("withQuery", () => {
  it("drops empty values rather than sending bare parameters", () => {
    // `?status=` is not "no filter" to FastAPI — it is an empty value it will
    // try to parse.
    expect(withQuery("/api/runs", { status: "", limit: 50, offset: 0 })).toBe(
      "/api/runs?limit=50&offset=0",
    );
    expect(withQuery("/api/runs", { status: undefined, run: null })).toBe("/api/runs");
  });

  it("keeps false, which is a real filter value", () => {
    expect(withQuery("/api/tickets", { is_eval_seed: false })).toBe("/api/tickets?is_eval_seed=false");
  });
});

describe("request", () => {
  it("attaches the stored bearer token", async () => {
    sessionStorage.setItem("flowforge.access_token", "tok-123");
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(json({ ok: true }));

    await api.get("/api/me");

    const init = fetchMock.mock.calls[0]![1] as RequestInit;
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer tok-123");
  });

  it("clears the session on 401 so a dead token cannot poison every later call", async () => {
    sessionStorage.setItem("flowforge.access_token", "expired");
    vi.spyOn(globalThis, "fetch").mockResolvedValue(json({ detail: "token has expired" }, 401));

    await expect(api.get("/api/me")).rejects.toBeInstanceOf(Unauthenticated);
    expect(sessionStorage.getItem("flowforge.access_token")).toBeNull();
  });

  it("carries the server's detail onto the error", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      json({ detail: "this approval was already decided" }, 409),
    );

    await expect(api.post("/api/approvals/x/decision", {})).rejects.toMatchObject({
      status: 409,
      detail: "this approval was already decided",
    });
  });

  it("flattens FastAPI validation errors into something readable", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      json({ detail: [{ msg: "field required" }, { msg: "too short" }] }, 422),
    );

    await expect(api.post("/api/tickets", {})).rejects.toMatchObject({
      detail: "field required; too short",
    });
  });

  it("does not set Content-Type on an upload, so fetch can pick the boundary", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(json({ id: "1" }));
    const form = new FormData();
    form.append("file", new Blob(["x"]), "policy.md");

    await api.upload("/api/documents", form);

    const init = fetchMock.mock.calls[0]![1] as RequestInit;
    // Setting it by hand is the classic silent multipart failure.
    expect((init.headers as Record<string, string>)["Content-Type"]).toBeUndefined();
  });

  it("returns undefined for 204 rather than trying to parse a body", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(null, { status: 204 }));
    await expect(api.post("/api/logout")).resolves.toBeUndefined();
  });

  it("still raises ApiError when the body is not JSON", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response("<html>502 Bad Gateway</html>", { status: 502, statusText: "Bad Gateway" }),
    );
    await expect(api.get("/api/runs")).rejects.toBeInstanceOf(ApiError);
  });
});
