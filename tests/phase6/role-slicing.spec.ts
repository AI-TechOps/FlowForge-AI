import { expect, test, type Page } from "@playwright/test";

import { currentAccessToken, isApiResponse, loginAs, PERSONAS, TID } from "./helpers";

const NAV = {
  dashboard: TID.navLink("dashboard"),
  documents: TID.navLink("documents"),
  tickets: TID.navLink("tickets"),
  approvals: TID.navLink("approvals"),
  evaluation: TID.navLink("evaluation"),
  audit: TID.navLink("audit"),
  config: TID.navLink("config"),
} as const;

const EXPECTED_NAV = {
  administrator: [
    NAV.dashboard,
    NAV.documents,
    NAV.tickets,
    NAV.approvals,
    NAV.evaluation,
    NAV.audit,
    NAV.config,
  ],
  operator: [NAV.dashboard, NAV.tickets, NAV.config],
  approver: [NAV.dashboard, NAV.tickets, NAV.approvals, NAV.config],
} as const;

async function expectNav(page: Page, visibleIds: readonly string[]): Promise<void> {
  const visible = new Set(visibleIds);
  for (const testId of Object.values(NAV)) {
    if (visible.has(testId)) {
      await expect(page.getByTestId(testId)).toBeVisible();
    } else {
      await expect(page.getByTestId(testId)).toHaveCount(0);
    }
  }
}

for (const role of ["administrator", "operator", "approver"] as const) {
  test(`G6.2 ${role} receives the specified navigation and dashboard slice`, async ({ page }) => {
    const responsePromise = page.waitForResponse((response) =>
      isApiResponse(response, "GET", "/api/metrics/summary"),
    );
    await loginAs(page, PERSONAS[role]);
    const response = await responsePromise;
    expect(response.status()).toBe(200);
    const metrics = (await response.json()) as Record<string, unknown>;

    await expectNav(page, EXPECTED_NAV[role]);
    await expect(page.getByTestId(TID.metric("avg_tokens_per_run"))).toBeVisible();

    if (role === "administrator") {
      expect(metrics).toHaveProperty("estimated_cost_usd");
      expect(metrics).toHaveProperty("evaluation_accuracy");
      await expect(page.getByTestId(TID.metric("estimated_cost_usd"))).toBeVisible();
      await expect(page.getByTestId(TID.metric("evaluation_accuracy"))).toBeVisible();
    } else {
      expect(metrics).not.toHaveProperty("estimated_cost_usd");
      expect(metrics).not.toHaveProperty("evaluation_accuracy");
      await expect(page.getByTestId(TID.metric("estimated_cost_usd"))).toHaveCount(0);
      await expect(page.getByTestId(TID.metric("evaluation_accuracy"))).toHaveCount(0);
    }
  });
}

test("G6.2 a hidden route refuses direct navigation and its API still rejects the role", async ({
  browser,
}) => {
  const adminContext = await browser.newContext();
  const adminPage = await adminContext.newPage();
  await loginAs(adminPage, PERSONAS.administrator);
  const documentsHref = await adminPage.getByTestId(NAV.documents).getAttribute("href");
  const auditHref = await adminPage.getByTestId(NAV.audit).getAttribute("href");
  expect(documentsHref).toBeTruthy();
  expect(auditHref).toBeTruthy();
  await adminContext.close();

  const operatorContext = await browser.newContext();
  const operatorPage = await operatorContext.newPage();
  await loginAs(operatorPage, PERSONAS.operator);
  const operatorToken = await currentAccessToken(operatorPage);
  await operatorPage.goto(documentsHref!);
  await expect(operatorPage.getByTestId(TID.forbidden)).toBeVisible();
  const documentsApi = await operatorPage.request.get("/api/documents", {
    headers: { Authorization: `Bearer ${operatorToken}` },
  });
  expect(documentsApi.status()).toBe(403);
  await operatorContext.close();

  const approverContext = await browser.newContext();
  const approverPage = await approverContext.newPage();
  await loginAs(approverPage, PERSONAS.approver);
  const approverToken = await currentAccessToken(approverPage);
  await approverPage.goto(auditHref!);
  await expect(approverPage.getByTestId(TID.forbidden)).toBeVisible();
  const auditApi = await approverPage.request.get("/api/audit", {
    headers: { Authorization: `Bearer ${approverToken}` },
  });
  expect(auditApi.status()).toBe(403);
  await approverContext.close();
});
