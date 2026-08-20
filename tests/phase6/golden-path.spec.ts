import { randomUUID } from "node:crypto";

import { expect, test, type Page } from "@playwright/test";

import {
  dynamicTestIds,
  isApiResponse,
  jsonObject,
  loginAs,
  logout,
  PERSONAS,
  resourceId,
  setControl,
  TID,
} from "./helpers";

const UUID_SUFFIX = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

async function editAProposal(page: Page, marker: string): Promise<{
  index: number;
  original: string;
  edited: string;
}> {
  await page.getByTestId(TID.openEdit).click();
  await expect(page.getByTestId(TID.editForm)).toBeVisible();

  const controls = page.locator('[data-testid^="edit-value-"]');
  const count = await controls.count();
  expect(count, "the edit form must expose at least one validated proposal value").toBeGreaterThan(0);

  let chosenIndex = -1;
  for (let index = 0; index < count; index += 1) {
    const control = controls.nth(index);
    const tagName = await control.evaluate((element) => element.tagName.toLowerCase());
    const inputType = (await control.getAttribute("type")) ?? "text";
    if (tagName === "textarea" || (tagName === "input" && inputType === "text")) {
      chosenIndex = index;
      break;
    }
  }
  if (chosenIndex < 0) chosenIndex = 0;

  const control = page.getByTestId(TID.editValue(chosenIndex));
  const original = await control.inputValue();
  const tagName = await control.evaluate((element) => element.tagName.toLowerCase());
  let edited: string;
  if (tagName === "select") {
    const options = await control.locator("option").evaluateAll((nodes) =>
      nodes
        .map((node) => ({
          value: (node as HTMLOptionElement).value,
          disabled: (node as HTMLOptionElement).disabled,
        }))
        .filter((option) => !option.disabled && option.value !== ""),
    );
    const replacement = options.find((option) => option.value !== original);
    expect(replacement, "an enum edit needs a second valid option").toBeTruthy();
    edited = replacement!.value;
    await control.selectOption(edited);
  } else {
    edited = `Phase 6 approved edit ${marker}`;
    await control.fill(edited);
  }

  return { index: chosenIndex, original, edited };
}

test("G6.1/G6.3/G6.4 the browser completes the ten-step MVP journey", async ({ page }) => {
  test.setTimeout(300_000);
  const marker = `phase6-${randomUUID()}`;

  await test.step("administrator logs in, uploads policy, and sees indexing complete", async () => {
    await loginAs(page, PERSONAS.administrator);
    await page.getByTestId(TID.navLink("documents")).click();
    await expect(page.getByTestId(TID.documents)).toBeVisible();
    await page.getByTestId(TID.uploadOpen).click();
    await page.getByTestId(TID.uploadInput).setInputFiles({
      name: `${marker}.md`,
      mimeType: "text/markdown",
      buffer: Buffer.from(
        `# MeridianConnect VPN recovery ${marker}\n\n` +
          "When a Meridian Dynamics employee cannot connect to MeridianConnect VPN, " +
          "route the ticket to IT Infrastructure, set priority P2, ask the employee " +
          "to retry MFA, and add an internal note recording the recovery steps.",
      ),
    });
    const uploadResponsePromise = page.waitForResponse((response) =>
      isApiResponse(response, "POST", "/api/documents"),
    );
    await page.getByTestId(TID.uploadSubmit).click();
    const uploadResponse = await uploadResponsePromise;
    expect([200, 201, 202]).toContain(uploadResponse.status());
    const documentId = resourceId(await jsonObject(uploadResponse), "document");
    await expect(page.getByTestId(TID.documentRow(documentId))).toBeVisible();
    await expect(page.getByTestId(TID.documentStatus(documentId))).toContainText(/ready/i, {
      timeout: 90_000,
    });
  });

  await logout(page);

  let ticketId = "";
  let runId = "";
  let runUrl = "";
  await test.step("operator files the VPN ticket and starts triage", async () => {
    await loginAs(page, PERSONAS.operator);
    await page.getByTestId(TID.navLink("tickets")).click();
    await page.getByTestId(TID.newTicketOpen).click();
    await expect(page.getByTestId(TID.newTicketForm)).toBeVisible();
    await page.getByTestId(TID.newTicketTitle).fill(`VPN access failure ${marker}`);
    await page
      .getByTestId(TID.newTicketDescription)
      .fill(
        `Employee cannot connect to MeridianConnect VPN. MFA retry did not help. ${marker}`,
      );
    await setControl(
      page.getByTestId(TID.newTicketDepartment),
      "Information Technology",
    );
    await setControl(page.getByTestId(TID.newTicketService), "MeridianConnect VPN");
    await setControl(page.getByTestId(TID.newTicketPriority), "P3");

    const createResponsePromise = page.waitForResponse((response) =>
      isApiResponse(response, "POST", "/api/tickets"),
    );
    await page.getByTestId(TID.newTicketSubmit).click();
    const createResponse = await createResponsePromise;
    expect([200, 201]).toContain(createResponse.status());
    ticketId = resourceId(await jsonObject(createResponse), "ticket");

    await expect(page.getByTestId(TID.ticketRow(ticketId))).toContainText(marker);
    const triageResponsePromise = page.waitForResponse((response) =>
      isApiResponse(response, "POST", "/api/runs"),
    );
    await page.getByTestId(TID.ticketTriage(ticketId)).click();
    const triageResponse = await triageResponsePromise;
    expect([200, 201, 202]).toContain(triageResponse.status());
    runId = resourceId(await jsonObject(triageResponse), "run");

    await expect(page.getByTestId(TID.runDetail)).toBeVisible();
    runUrl = page.url();
    await expect(page.getByTestId(TID.runStatus)).toContainText(/awaiting.approval/i, {
      timeout: 120_000,
    });
  });

  await test.step("run detail proves every rendered citation resolves to stored evidence", async () => {
    await expect(page.getByTestId(TID.evidencePanel)).toBeVisible();
    await expect(page.getByTestId(TID.citationList)).toBeVisible();
    const citationIds = (
      await page.getByTestId(TID.citationList).locator('[data-testid^="citation-"]').evaluateAll(
        (elements) => elements.map((element) => element.getAttribute("data-testid") ?? ""),
      )
    )
      .filter((testId) => testId !== TID.citationList)
      .filter((testId) => !testId.startsWith("citation-unresolved-"))
      .map((testId) => testId.slice("citation-".length));

    expect(citationIds.length, "a completed triage proposal needs at least one citation").toBeGreaterThan(0);
    for (const chunkId of citationIds) {
      await expect(page.getByTestId(TID.citation(chunkId))).toBeVisible();
      await expect(page.getByTestId(TID.evidenceItem(chunkId))).toBeVisible();
      await expect
        .soft(page.getByTestId(TID.evidenceCited(chunkId)))
        .toBeVisible({ timeout: 1_000 });
      await expect.soft(page.getByTestId(TID.citationUnresolved(chunkId))).toHaveCount(0);
    }
    await expect.soft(page.locator('[data-testid^="citation-unresolved-"]')).toHaveCount(0);
  });

  await logout(page);

  let approvalId = "";
  let originalEdit = "";
  let editedValue = "";
  await test.step("a distinct approver edits and authorizes the proposal", async () => {
    await loginAs(page, PERSONAS.approver);
    const inboxResponsePromise = page.waitForResponse((response) =>
      isApiResponse(response, "GET", "/api/approvals"),
    );
    await page.getByTestId(TID.navLink("approvals")).click();
    await expect(page.getByTestId(TID.approvalInbox)).toBeVisible();
    const inboxResponse = await inboxResponsePromise;
    expect(inboxResponse.status()).toBe(200);
    const inboxPayload: unknown = await inboxResponse.json();
    const approvals = Array.isArray(inboxPayload)
      ? inboxPayload
      : ((inboxPayload as Record<string, unknown>).approvals as unknown[] | undefined);
    expect(Array.isArray(approvals)).toBe(true);
    const approval = approvals!.find((candidate) => {
      if (!candidate || typeof candidate !== "object") return false;
      const row = candidate as Record<string, unknown>;
      const run = row.run;
      return (
        row.run_id === runId ||
        (run !== null &&
          typeof run === "object" &&
          (run as Record<string, unknown>).id === runId)
      );
    }) as Record<string, unknown> | undefined;
    expect(approval, `approval inbox has no card for run ${runId}`).toBeTruthy();
    expect(typeof approval!.id).toBe("string");
    approvalId = approval!.id as string;
    await page.getByTestId(TID.approvalRow(approvalId)).click();
    await expect(page.getByTestId(TID.approvalCard)).toBeVisible();
    await expect(page.getByTestId(TID.approvalConfidence)).not.toHaveText("");
    await expect(page.getByTestId(TID.approvalRisk)).not.toHaveText("");
    await expect(page.getByTestId(TID.approvalAgentVersion)).not.toHaveText("");

    const edit = await editAProposal(page, marker);
    originalEdit = edit.original;
    editedValue = edit.edited;
    const decisionResponsePromise = page.waitForResponse((response) =>
      isApiResponse(response, "POST", new RegExp(`/api/approvals/${approvalId}/decision$`)),
    );
    await page.getByTestId(TID.editSubmit).click();
    const decisionResponse = await decisionResponsePromise;
    expect(decisionResponse.status()).toBe(200);
  });

  await logout(page);

  await test.step("the approved write completes and the ticket is actioned", async () => {
    await loginAs(page, PERSONAS.operator);
    await page.goto(runUrl);
    await expect(page.getByTestId(TID.runDetail)).toBeVisible();
    await expect(page.getByTestId(TID.runStatus)).toContainText(/completed/i, {
      timeout: 120_000,
    });
    await page.getByTestId(TID.navLink("tickets")).click();
    await expect
      .soft(page.getByTestId(TID.ticketStatus(ticketId)))
      .toContainText(/actioned/i, { timeout: 5_000 });
  });

  await logout(page);

  await test.step("dashboard and expanded audit rows show the completed edited workflow", async () => {
    await loginAs(page, PERSONAS.administrator);
    await expect(page.getByTestId(TID.dashboard)).toBeVisible();
    await expect(page.getByTestId(TID.recentRuns)).toContainText(runId.slice(0, 8));
    const totalRunsText = await page.getByTestId(TID.metricValue("total_runs")).innerText();
    expect(Number(totalRunsText.replace(/[^0-9.]/g, ""))).toBeGreaterThan(0);

    await page.getByTestId(TID.navLink("audit")).click();
    await expect(page.getByTestId(TID.audit)).toBeVisible();
    await page.getByTestId(TID.auditFilterRun).fill(runId);
    await page.getByTestId(TID.auditFilterRun).press("Enter");

    await expect
      .poll(async () => (await dynamicTestIds(page, "audit-")).filter((id) => UUID_SUFFIX.test(id.slice(6))).length)
      .toBeGreaterThan(0);
    const rowIds = (await dynamicTestIds(page, "audit-")).filter((id) =>
      UUID_SUFFIX.test(id.slice("audit-".length)),
    );
    const decisionRowId = (
      await Promise.all(
        rowIds.map(async (testId) => ({
          testId,
          text: (await page.getByTestId(testId).innerText()).toLowerCase(),
        })),
      )
    ).find((row) => row.text.includes("approval.decision"))?.testId;
    expect(decisionRowId, "audit has no approval.decision row for the edited run").toBeTruthy();
    const auditId = decisionRowId!.slice("audit-".length);
    await page.getByTestId(TID.auditExpand(auditId)).click();
    const decisionJson = (await page.getByTestId(TID.auditJson(auditId)).innerText()).replace(
      /\s+/g,
      " ",
    );
    expect(decisionJson).toContain(editedValue);
    if (originalEdit !== "") expect(decisionJson).toContain(originalEdit);
    expect(decisionJson.toLowerCase()).toContain("edit");

    const auditText = (await page.getByTestId(TID.audit).innerText()).toLowerCase();
    for (const event of [
      "get_ticket",
      "search_company_knowledge",
      "llm.classify",
      "approval.decision",
      ".confirm",
    ]) {
      expect(auditText).toContain(event);
    }
  });
});
