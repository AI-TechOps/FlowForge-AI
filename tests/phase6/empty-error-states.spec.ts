import { expect, test, type Locator, type Page } from "@playwright/test";

import {
  currentSessionTemplate,
  installAccessToken,
  issueLocalToken,
  loginAs,
  PERSONAS,
  seedFreshAllRolesTenant,
  TID,
} from "./helpers";

async function expectEmpty(root: Locator): Promise<void> {
  await expect(root).toBeVisible();
  await expect(root.getByTestId(TID.empty).first()).toBeVisible();
  await expect(root.getByTestId(TID.loading)).toHaveCount(0);
  await expect(root.getByTestId(TID.error)).toHaveCount(0);
}

async function openNav(page: Page, route: string): Promise<void> {
  await page.getByTestId(TID.navLink(route)).click();
}

test("G6.5 a fresh organization has explicit empty states on every collection screen", async ({
  page,
}) => {
  test.setTimeout(150_000);

  await loginAs(page, PERSONAS.allRoles);
  const sessionTemplate = await currentSessionTemplate(page);
  const tenant = seedFreshAllRolesTenant();
  const token = await issueLocalToken(page, tenant);
  await installAccessToken(page, sessionTemplate, token);
  await page.goto("/");
  await expect(page.getByTestId(TID.userEmail)).toContainText(tenant.email);

  await expectEmpty(page.getByTestId(TID.recentRuns));

  await openNav(page, "documents");
  await expectEmpty(page.getByTestId(TID.documents));

  await openNav(page, "tickets");
  await expectEmpty(page.getByTestId(TID.tickets));

  await openNav(page, "approvals");
  await expectEmpty(page.getByTestId(TID.approvalInbox));

  await openNav(page, "evaluation");
  await expectEmpty(page.getByTestId(TID.evaluation));

  await openNav(page, "audit");
  await expectEmpty(page.getByTestId(TID.audit));
});

const FAILURE_CASES = [
  {
    name: "dashboard",
    route: "dashboard",
    api: "**/api/metrics/summary*",
  },
  {
    name: "documents",
    route: "documents",
    api: "**/api/documents*",
  },
  {
    name: "tickets",
    route: "tickets",
    api: "**/api/tickets*",
  },
  {
    name: "approval inbox",
    route: "approvals",
    api: "**/api/approvals*",
  },
  {
    name: "evaluation",
    route: "evaluation",
    api: "**/api/eval/batches*",
  },
  {
    name: "audit",
    route: "audit",
    api: "**/api/audit*",
  },
  {
    name: "agent configuration",
    route: "config",
    api: "**/api/config/agent*",
  },
] as const;

for (const failureCase of FAILURE_CASES) {
  test(`G6.5 ${failureCase.name} renders an error when its backend request cannot connect`, async ({
    page,
  }) => {
    await page.goto("/login");
    await page.route(failureCase.api, (route) => route.abort("connectionrefused"));
    await page.getByTestId(TID.loginIdentity(PERSONAS.allRoles)).click();
    await expect(page.getByTestId(TID.app)).toBeVisible();
    if (failureCase.route !== "dashboard") {
      await openNav(page, failureCase.route);
    }

    await expect(page.getByTestId(TID.app)).toBeVisible();
    await expect(page.getByTestId(TID.error).first()).toBeVisible();
    await expect(page.getByTestId(TID.loading)).toHaveCount(0);
  });
}
