import { expect, test, type Page, type Route } from "@playwright/test";

import { loginAs, PERSONAS, TID } from "../phase6/helpers";

const RUN_ID = "11111111-1111-4111-8111-111111111111";
const TICKET_ID = "22222222-2222-4222-8222-222222222222";
const APPROVAL_ID = "33333333-3333-4333-8333-333333333333";

function isoDaysAgo(days: number): string {
  return new Date(Date.now() - days * 24 * 60 * 60 * 1000).toISOString();
}

async function mockRunDetail(page: Page): Promise<void> {
  await page.route(`**/api/runs/${RUN_ID}`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: RUN_ID,
        ticket_id: TICKET_ID,
        status: "completed",
        agent_version: "triage-v1",
        confidence: 0.91,
        output: {
          category: "access",
          urgency: "medium",
          recommended_team: "IT Security",
          suggested_priority: "P2",
          summary: "Grounded result",
          recommended_resolution: "Reset access through the documented process.",
          citations: [{ chunk_id: "chunk-1" }],
          executed_actions: [],
        },
        evidence: [
          {
            chunk_id: "chunk-1",
            document_title: "Identity Access Standard",
            page: 4,
            section: "Recovery",
            score: 0.92,
            text: "Use the approved recovery workflow.",
          },
        ],
        audit_entries: [
          {
            actor: "agent",
            tool: "llm.complete",
            payload: { model: "fake" },
            result: { ok: true },
            latency_ms: 12,
            tokens_in: 10,
            tokens_out: 8,
            cost_estimate: 0,
            created_at: new Date().toISOString(),
          },
        ],
        created_at: new Date().toISOString(),
      }),
    });
  });
  await page.route(`**/api/tickets/${TICKET_ID}`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: TICKET_ID,
        title: "Affected identity ticket",
        description: "Cannot access the account",
        status: "actioned",
        department: "Finance",
        service: "Identity",
        priority: "P2",
        assigned_team: "IT Security",
      }),
    });
  });
}

async function mockApprovalInbox(page: Page, onDecision?: (route: Route) => Promise<void>) {
  await page.route("**/api/approvals**", async (route) => {
    const url = new URL(route.request().url());
    if (route.request().method() === "POST" && url.pathname.endsWith("/decision")) {
      if (onDecision) return onDecision(route);
      return route.fulfill({ status: 500, body: "unexpected decision" });
    }

    const detail = {
      id: APPROVAL_ID,
      run_id: RUN_ID,
      ticket_id: TICKET_ID,
      status: "pending",
      risk_class: "medium",
      confidence: 0.91,
      agent_version: "triage-v1",
      original_proposal: [
        {
          tool: "change_ticket_priority",
          field: "priority",
          current_value: "P3",
          new_value: "P2",
          args: { priority: "P2" },
        },
      ],
      created_at: new Date().toISOString(),
    };
    const body = url.pathname === `/api/approvals/${APPROVAL_ID}` ? detail : [detail];
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(body),
    });
  });
}

test("a 401 from any data view clears the live session and returns to login", async ({ page }) => {
  await loginAs(page, PERSONAS.operator);
  await page.route("**/api/tickets**", async (route) => {
    await route.fulfill({
      status: 401,
      contentType: "application/json",
      body: JSON.stringify({ detail: "expired adversarial session" }),
    });
  });

  await page.getByTestId(TID.navLink("tickets")).click();

  await expect
    .poll(() => page.evaluate(() => sessionStorage.getItem("flowforge.access_token")))
    .toBeNull();
  await expect(page.getByTestId(TID.loginCard)).toBeVisible();
  await expect(page.getByTestId(TID.app)).toHaveCount(0);
});

test("the required ticket filters include requester department", async ({ page }) => {
  await loginAs(page, PERSONAS.operator);
  await page.getByTestId(TID.navLink("tickets")).click();
  await expect(page.getByTestId(TID.tickets)).toBeVisible();

  await expect(page.getByLabel(/filter by department/i)).toBeVisible();
});

test("the audit log exposes both ends of its required date range", async ({ page }) => {
  await loginAs(page, PERSONAS.administrator);
  await page.getByTestId(TID.navLink("audit")).click();
  await expect(page.getByTestId(TID.audit)).toBeVisible();

  const dateFilters = page.locator(
    'input[type="date"], input[type="datetime-local"], input[aria-label*="date" i], input[aria-label*="since" i], input[aria-label*="until" i]',
  );
  await expect(dateFilters).toHaveCount(2);
});

test("any persona sees the audit entries embedded in run detail", async ({ page }) => {
  await loginAs(page, PERSONAS.operator);
  await mockRunDetail(page);

  await page.goto(`/runs/${RUN_ID}`);
  await expect(page.getByTestId(TID.runDetail)).toBeVisible();
  await expect(page.getByTestId(TID.runAudit)).toBeVisible();
  await expect(page.getByTestId(TID.runAudit)).toContainText("llm.complete");
});

test("an approval card identifies the ticket whose state will change", async ({ page }) => {
  await loginAs(page, PERSONAS.approver);
  await mockApprovalInbox(page);
  await mockRunDetail(page);

  await page.goto("/approvals");
  const card = page.getByTestId(TID.approvalCard);
  await expect(card).toBeVisible();
  await expect(card).toContainText(TICKET_ID);
});

test("the edit form rejects an invalid typed value before POSTing a decision", async ({ page }) => {
  let decisionPosts = 0;
  await loginAs(page, PERSONAS.approver);
  await mockApprovalInbox(page, async (route) => {
    decisionPosts += 1;
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ id: APPROVAL_ID, status: "decided", decision: "edited" }),
    });
  });
  await mockRunDetail(page);

  await page.goto("/approvals");
  await expect(page.getByTestId(TID.approvalCard)).toBeVisible();
  await page.getByTestId(TID.openEdit).click();
  await page.getByTestId(TID.editValue(0)).fill("P99-not-a-priority");

  const posted = page
    .waitForRequest(
      (request) =>
        request.method() === "POST" &&
        new URL(request.url()).pathname === `/api/approvals/${APPROVAL_ID}/decision`,
      { timeout: 1_000 },
    )
    .then(() => true)
    .catch(() => false);
  await page.getByTestId(TID.editSubmit).click();

  expect(await posted, "invalid enum input reached the decision endpoint").toBe(false);
  expect(decisionPosts).toBe(0);
  await expect(page.getByTestId(TID.editForm)).toBeVisible();
});

test("dashboard outcome data follows the selected 7-day window", async ({ page }) => {
  const runs = [
    {
      id: RUN_ID,
      ticket_id: TICKET_ID,
      status: "failed",
      created_at: isoDaysAgo(1),
    },
    {
      id: "44444444-4444-4444-8444-444444444444",
      ticket_id: TICKET_ID,
      status: "completed",
      created_at: isoDaysAgo(20),
    },
  ];
  await page.route("**/api/runs?**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ total: runs.length, limit: 200, offset: 0, runs }),
    });
  });
  await page.route("**/api/metrics/summary?**", async (route) => {
    const days = Number(new URL(route.request().url()).searchParams.get("window_days") ?? "30");
    const total = days === 7 ? 1 : 2;
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        window_days: days,
        total_runs: total,
        successful_runs: days === 7 ? 0 : 1,
        failed_runs: 1,
        waiting_approvals: 0,
        avg_latency_seconds: 1,
        avg_tokens_per_run: 10,
        tool_success_rate: 1,
        approval_rate: null,
        human_edit_rate: null,
        human_rejection_rate: null,
        retrieval_success: 1,
        grounded_rate: 1,
        latest_eval_batch_id: null,
      }),
    });
  });

  await loginAs(page, PERSONAS.operator);
  await expect(page.getByTestId(TID.categoryDonut).locator(".donut__value")).toHaveText("2");
  await page.getByTestId(TID.windowSelect).getByRole("button", { name: "7d" }).click();
  await expect(page.getByTestId(TID.metricValue("total_runs"))).toHaveText("1");
  await expect(page.getByTestId(TID.categoryDonut).locator(".donut__value")).toHaveText("1");
});
