/**
 * Role gating and the metric contract — the two things most worth asserting
 * without a browser, because both are about what a screen does *not* show.
 */

import { describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";

import { NAV, RequireRole, canSee } from "./Shell";
import { Dashboard } from "../screens/Dashboard";
import { TID } from "../testids";
import { identityWith, renderWith, stubFetch } from "../test/render";

describe("nav visibility mirrors the server's role dependencies", () => {
  const routesFor = (roles: Parameters<typeof identityWith>) =>
    NAV.filter((item) => canSee(item, roles)).map((i) => i.route || "dashboard");

  it("gives an operator the shared screens and nothing administrative", () => {
    const routes = routesFor(["operator"]);
    expect(routes).toEqual(["dashboard", "tickets", "runs", "config"]);
    expect(routes).not.toContain("audit");
    expect(routes).not.toContain("evaluation");
    expect(routes).not.toContain("documents");
    expect(routes).not.toContain("approvals");
  });

  it("gives an approver the inbox but no administration", () => {
    const routes = routesFor(["approver"]);
    expect(routes).toContain("approvals");
    expect(routes).not.toContain("documents");
    expect(routes).not.toContain("audit");
  });

  it("gives an administrator everything", () => {
    expect(routesFor(["administrator"])).toEqual(NAV.map((i) => i.route || "dashboard"));
  });

  it("shows a screen to anyone holding any one of its roles", () => {
    const approvals = NAV.find((i) => i.route === "approvals")!;
    expect(canSee(approvals, ["operator", "approver"])).toBe(true);
    expect(canSee(approvals, ["operator"])).toBe(false);
  });
});

describe("RequireRole", () => {
  it("renders the screen when the role matches", () => {
    renderWith(
      <RequireRole roles={["administrator"]}>
        <p>secret</p>
      </RequireRole>,
      { identity: identityWith("administrator") },
    );
    expect(screen.getByText("secret")).toBeInTheDocument();
  });

  it("refuses — and explains — rather than redirecting", () => {
    renderWith(
      <RequireRole roles={["administrator"]}>
        <p>secret</p>
      </RequireRole>,
      { identity: identityWith("operator") },
    );
    expect(screen.queryByText("secret")).not.toBeInTheDocument();
    expect(screen.getByTestId(TID.forbidden)).toBeInTheDocument();
    // A redirect would make a mis-remembered bookmark look like a bug; the
    // refusal names the role it needs.
    expect(screen.getByTestId(TID.forbidden)).toHaveTextContent("administrator");
  });
});

const METRICS_SHARED = {
  window_days: 30,
  total_runs: 4,
  successful_runs: 3,
  failed_runs: 1,
  waiting_approvals: 0,
  avg_latency_seconds: 1.5,
  avg_tokens_per_run: 30,
  tool_success_rate: 1,
  approval_rate: null,
  human_edit_rate: null,
  human_rejection_rate: null,
  retrieval_success: 0.9,
  grounded_rate: 1,
  latest_eval_batch_id: null,
};

describe("Dashboard renders the payload it was given", () => {
  it("shows tokens to an operator and never invents cost", async () => {
    // Exactly what the API sends a non-administrator: the admin-only keys are
    // absent, not null (D19 decision 6 as amended by D20).
    stubFetch({
      "/api/metrics/summary": METRICS_SHARED,
      "/api/runs": { total: 0, limit: 8, offset: 0, runs: [] },
    });
    renderWith(<Dashboard />, { identity: identityWith("operator") });

    expect(await screen.findByTestId(TID.metricValue("avg_tokens_per_run"))).toHaveTextContent("30");
    expect(screen.queryByTestId(TID.metric("estimated_cost_usd"))).not.toBeInTheDocument();
    expect(screen.queryByTestId(TID.metric("evaluation_accuracy"))).not.toBeInTheDocument();
  });

  it("shows cost and eval accuracy when the API includes them", async () => {
    stubFetch({
      "/api/metrics/summary": {
        ...METRICS_SHARED,
        estimated_cost_usd: 0.1234,
        evaluation_accuracy: 0.5,
        cost_pricing_as_of: "2026-08-16",
      },
      "/api/runs": { total: 0, limit: 8, offset: 0, runs: [] },
    });
    renderWith(<Dashboard />, { identity: identityWith("administrator") });

    expect(await screen.findByTestId(TID.metricValue("estimated_cost_usd"))).toHaveTextContent(
      "$0.1234",
    );
    expect(screen.getByTestId(TID.metricValue("evaluation_accuracy"))).toHaveTextContent("50.0%");
  });

  it("says 'no data yet' for a null rate instead of 0.0%", async () => {
    stubFetch({
      "/api/metrics/summary": METRICS_SHARED,
      "/api/runs": { total: 0, limit: 8, offset: 0, runs: [] },
    });
    renderWith(<Dashboard />, { identity: identityWith("operator") });

    // "0.0%" would be a lie somebody could act on: nothing has been approved,
    // which is not the same as everything having been rejected.
    const rate = await screen.findByTestId(TID.metricValue("approval_rate"));
    expect(rate).toHaveTextContent("No data yet");
    expect(rate).not.toHaveTextContent("0.0%");
  });

  it("renders an error state, not a blank screen, when metrics fail", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ detail: "database is on fire" }), {
        status: 500,
        headers: { "Content-Type": "application/json" },
      }),
    );
    renderWith(<Dashboard />, { identity: identityWith("administrator") });

    expect(await screen.findByTestId(TID.error)).toBeInTheDocument();
    // The server's detail reaches the user; "Request failed" would not.
    expect(screen.getByTestId(TID.errorDetail)).toHaveTextContent("database is on fire");
  });
});
