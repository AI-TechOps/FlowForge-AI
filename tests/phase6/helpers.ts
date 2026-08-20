import { execFileSync } from "node:child_process";
import { randomUUID } from "node:crypto";

import {
  expect,
  type APIResponse,
  type Locator,
  type Page,
  type Response,
} from "@playwright/test";

import { TID } from "../../frontend/src/testids";

export { TID };

export const PERSONAS = {
  administrator: "admin@demo",
  operator: "operator@demo",
  approver: "approver@demo",
  allRoles: "demo@demo",
} as const;

const JWT_PATTERN = /eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+/;

export async function loginAs(page: Page, email: string): Promise<void> {
  await page.goto("/login");
  await page.getByTestId(TID.loginIdentity(email)).click();
  await expect(page.getByTestId(TID.app)).toBeVisible();
  await expect(page.getByTestId(TID.sidebar)).toBeVisible();
  await expect(page.getByTestId(TID.userEmail)).toContainText(email);
}

export async function logout(page: Page): Promise<void> {
  const userMenu = page.getByTestId(TID.userMenu);
  if ((await userMenu.count()) > 0 && (await userMenu.isVisible())) {
    await userMenu.click();
  }
  await page.getByTestId(TID.signOut).click();
  await expect(page.getByTestId(TID.loginCard)).toBeVisible();
}

export function isApiResponse(
  response: Response,
  method: string,
  pathname: string | RegExp,
): boolean {
  const url = new URL(response.url());
  return (
    response.request().method() === method &&
    (typeof pathname === "string" ? url.pathname === pathname : pathname.test(url.pathname))
  );
}

export async function jsonObject(
  response: APIResponse | Response,
): Promise<Record<string, unknown>> {
  const payload: unknown = await response.json();
  expect(payload).not.toBeNull();
  expect(typeof payload).toBe("object");
  expect(Array.isArray(payload)).toBe(false);
  return payload as Record<string, unknown>;
}

export function resourceId(payload: Record<string, unknown>, ...wrappers: string[]): string {
  let candidate = payload;
  for (const wrapper of wrappers) {
    const nested = payload[wrapper];
    if (nested && typeof nested === "object" && !Array.isArray(nested)) {
      candidate = nested as Record<string, unknown>;
      break;
    }
  }
  expect(typeof candidate.id).toBe("string");
  expect(candidate.id).not.toBe("");
  return candidate.id as string;
}

export async function setControl(
  control: Locator,
  preferred: string,
  fallback?: string,
): Promise<void> {
  const tagName = await control.evaluate((element) => element.tagName.toLowerCase());
  if (tagName === "select") {
    const options = await control.locator("option").evaluateAll((nodes) =>
      nodes.map((node) => ({
        value: (node as HTMLOptionElement).value,
        label: (node.textContent ?? "").trim(),
        disabled: (node as HTMLOptionElement).disabled,
      })),
    );
    const preferredOption = options.find(
      (option) => !option.disabled && (option.value === preferred || option.label === preferred),
    );
    const fallbackOption = options.find(
      (option) =>
        !option.disabled &&
        option.value !== "" &&
        (fallback === undefined || option.value === fallback || option.label === fallback),
    );
    const chosen = preferredOption ?? fallbackOption;
    expect(chosen, `no selectable option on ${await control.getAttribute("data-testid")}`).toBeTruthy();
    await control.selectOption(chosen!.value);
    return;
  }
  await control.fill(preferred);
}

export async function currentAccessToken(page: Page): Promise<string> {
  const token = await page.evaluate((patternSource) => {
    const pattern = new RegExp(patternSource);
    for (const value of Object.values(sessionStorage)) {
      const match = value.match(pattern);
      if (match) return match[0];
    }
    return null;
  }, JWT_PATTERN.source);
  expect(token, "the authenticated SPA session did not retain its access token").toBeTruthy();
  return token!;
}

type SessionTemplate = { key: string; value: string };

export async function currentSessionTemplate(page: Page): Promise<SessionTemplate> {
  const entry = await page.evaluate((patternSource) => {
    const pattern = new RegExp(patternSource);
    return (
      Object.entries(sessionStorage).find(([, value]) => pattern.test(value)) ?? null
    );
  }, JWT_PATTERN.source);
  expect(entry, "could not find the authenticated token in sessionStorage").toBeTruthy();
  return { key: entry![0], value: entry![1] };
}

export async function installAccessToken(
  page: Page,
  template: SessionTemplate,
  accessToken: string,
): Promise<void> {
  const value = JWT_PATTERN.test(template.value)
    ? template.value.replace(JWT_PATTERN, accessToken)
    : accessToken;
  await page.evaluate(
    ({ key, storedValue }) => {
      sessionStorage.clear();
      sessionStorage.setItem(key, storedValue);
    },
    { key: template.key, storedValue: value },
  );
}

export type FreshTenant = {
  orgId: string;
  userId: string;
  email: string;
  subject: string;
};

export function seedFreshAllRolesTenant(): FreshTenant {
  const orgId = randomUUID();
  const userId = randomUUID();
  const suffix = orgId.slice(0, 8);
  const email = `phase6-empty-${suffix}@example.test`;
  const subject = `phase6|${randomUUID()}`;
  const sql = [
    `INSERT INTO organizations (id, name) VALUES ('${orgId}', 'Phase 6 Empty ${suffix}');`,
    `INSERT INTO users (id, org_id, email, auth_subject) VALUES ('${userId}', '${orgId}', '${email}', NULL);`,
    `INSERT INTO user_roles (user_id, role) VALUES ('${userId}', 'administrator'), ('${userId}', 'operator'), ('${userId}', 'approver');`,
  ].join(" ");
  const composeFile = process.env.COMPOSE_FILE ?? "infra/docker-compose.yml";
  execFileSync(
    "docker",
    [
      "compose",
      "-f",
      composeFile,
      "exec",
      "-T",
      "db",
      "psql",
      "-v",
      "ON_ERROR_STOP=1",
      "-U",
      "flowforge",
      "-d",
      "flowforge",
      "-c",
      sql,
    ],
    { encoding: "utf8" },
  );
  return { orgId, userId, email, subject };
}

export async function issueLocalToken(page: Page, tenant: FreshTenant): Promise<string> {
  const response = await page.request.post("/api/dev/token", {
    data: {
      email: tenant.email,
      subject: tenant.subject,
      org_id: tenant.orgId,
      expires_in_seconds: 3600,
    },
  });
  expect(response.status()).toBe(200);
  const payload = await jsonObject(response);
  expect(typeof payload.access_token).toBe("string");
  const token = payload.access_token as string;

  const me = await page.request.get("/api/me", {
    headers: { Authorization: `Bearer ${token}` },
  });
  expect(me.status()).toBe(200);
  return token;
}

export async function dynamicTestIds(page: Page, prefix: string): Promise<string[]> {
  return page.locator(`[data-testid^="${prefix}"]`).evaluateAll((elements) =>
    elements
      .map((element) => element.getAttribute("data-testid"))
      .filter((value): value is string => value !== null),
  );
}
