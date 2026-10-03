import { expect, type Page, test } from "@playwright/test";

async function signIn(page: Page, onboarded = true, autonomy = "assist") {
  const email = `pm-${Date.now()}-${Math.round(Math.random() * 1e6)}@company.test`;
  await page.request.post("/api/v1/auth/dev-login", { data: { email, name: "Yassine", title: "Head of AI" } });
  if (onboarded) await page.request.post("/api/v1/me/onboarding", { data: { title: "Head of AI", default_autonomy: autonomy } });
}

async function linkOrbit(page: Page) {
  const response = await page.request.post("/api/v1/me/orbit", { data: { email: "pm@orbit.test", password: "orbit-e2e" } });
  expect(response.ok()).toBeTruthy();
}

async function ask(page: Page, text: string, project?: string) {
  const composer = page.getByLabel("Ask NOVA");
  await composer.fill(text);
  if (project) {
    await page.getByLabel("Project").click();
    await page.getByRole("option", { name: project }).click();
  }
  await composer.press("Enter");
  await expect(page).toHaveURL(/\/c\//);
}

test("first run: Meet your NOVA, then a conversation with a cited answer", async ({ page }) => {
  await signIn(page, false);
  await page.goto("/");
  await expect(page).toHaveURL(/\/welcome/);
  await expect(page.getByText("What is your role?")).toBeVisible();
  await page.getByPlaceholder("e.g. Head of AI").fill("Head of AI");
  for (let i = 0; i < 5; i++) await page.getByRole("button", { name: /Continue/ }).click(); // role → … → autonomy → ORBIT
  await page.getByRole("button", { name: "Skip for now" }).click();
  await expect(page.getByText(/Your .* is ready\./)).toBeVisible();
  await page.getByRole("button", { name: "Start working" }).click();

  await expect(page.getByText(/, Yassine\./)).toBeVisible();
  await expect(page.getByRole("heading", { name: /Here's what matters/ })).toBeVisible();
  await expect(page.getByPlaceholder("Tell NOVA what you need…")).toBeVisible();
  await ask(page, "What is a good north star metric for an evaluation platform?");
  await expect(page.locator(".prose-nova").last()).toBeVisible();
  await expect(page.getByRole("button", { name: "Useful", exact: true })).toBeVisible();
});

test("PRD generation opens a structured, collapsible Artifact next to the conversation", async ({ page }) => {
  await signIn(page);
  await page.goto("/");
  await ask(page, "/prd Scheduled CSV exports of evaluation results for stakeholders");
  const panel = page.getByLabel("Artifact title");
  await expect(panel).toBeVisible();
  for (const section of ["Summary", "Functional requirements", "Success metrics", "Acceptance criteria", "Open questions"]) {
    await expect(page.getByRole("heading", { name: section, exact: true })).toBeVisible();
  }
  await expect(page.getByText(/Created \*\*|Created/).first()).toBeVisible();
});

test("Vision to Backlog uses ORBIT context with classification and citations", async ({ page }) => {
  await signIn(page);
  await linkOrbit(page);
  await page.goto("/");
  await ask(page, "Help me turn the FORGE vision into a backlog.", "FORGE");
  await expect(page.getByText("Using context from ORBIT")).toBeVisible();
  await expect(page.getByText("C2 · Confidential").first()).toBeVisible();
  await expect(page.getByLabel("Artifact title")).toHaveValue(/Backlog/);
  for (const section of ["Objectives", "Initiatives", "Epics", "User stories"]) {
    await expect(page.getByRole("heading", { name: section, exact: true })).toBeVisible();
  }
  await expect(page.getByRole("button", { name: "S1" }).first()).toBeVisible();
});

test("Sprint planning produces an editable Sprint Plan", async ({ page }) => {
  await signIn(page);
  await linkOrbit(page);
  await page.goto("/");
  await ask(page, "Prepare Sprint 19.", "FORGE");
  await expect(page.getByLabel("Artifact title")).toHaveValue(/Sprint Plan/);
  await expect(page.getByRole("heading", { name: "Sprint goal", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Committed scope", exact: true })).toBeVisible();
});

test("Conversational editing changes only the requested section and versions the Artifact", async ({ page }) => {
  await signIn(page);
  await page.goto("/");
  await ask(page, "/prd Audit log export for compliance teams, filtered by project and date");
  const title = page.getByLabel("Artifact title");
  await expect(title).toBeVisible();
  await expect(page.getByText("v1", { exact: true }).first()).toBeVisible();

  await ask(page, "Rewrite the success metrics to be measurable");
  await expect(page.getByText(/Updated/).first()).toBeVisible();
  await expect(page.getByText(/\/prd/).filter({ has: page.locator("strong") })).toHaveCount(0); // titles drop the /skill token
  await page.getByRole("button", { name: "Version history" }).click();
  await expect(page.getByText("v2", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("Success metrics").last()).toBeVisible();

  // Manual edit + autosave creates a new version (once the panel shows NOVA's v2)
  await expect(page.getByTestId("save-state")).toHaveText("v2");
  await title.fill("PRD · Audit log export (edited)");
  await expect(page.getByTestId("save-state")).toHaveText("Saved · v3", { timeout: 10_000 });
});

test("the full-page Artifact editor shows numbered sections, Ask NOVA actions and quality checks", async ({ page }) => {
  await signIn(page);
  await page.goto("/");
  await ask(page, "/prd Scheduled CSV exports of evaluation results for stakeholders");
  await expect(page.getByLabel("Artifact title")).toBeVisible();
  const id = await page.evaluate(async () => {
    const list = await fetch("/api/v1/artifacts").then((r) => r.json());
    return list[0].id as string;
  });
  await page.goto(`/artifacts/${id}`);
  await expect(page.getByRole("tab", { name: "Write" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "1. Summary" })).toBeVisible();
  await expect(page.getByText("Quality check")).toBeVisible();
  await page.getByRole("button", { name: "Ask NOVA" }).first().click();
  for (const action of ["Improve writing", "Challenge assumptions", "Add evidence", "Summarize", "Custom instruction…"]) {
    await expect(page.getByRole("menuitem", { name: action })).toBeVisible();
  }
  await page.keyboard.press("Escape");

  // A status change is a decision: it shows up in Activity → Decisions.
  await page.getByRole("button", { name: "More" }).click();
  await page.getByRole("menuitem", { name: /Mark as Final/ }).click();
  await page.goto("/activity");
  await page.getByRole("tab", { name: "Decisions" }).click();
  await expect(page.getByText(/as final$/)).toBeVisible();
  await expect(page.getByRole("link", { name: "View artifact" }).first()).toBeVisible();

  await page.goto("/library");
  await expect(page).toHaveURL(/\/artifacts/);
  await expect(page.getByRole("navigation", { name: "Library" })).toBeVisible();
});

test("the slash menu stays inside the viewport, below the composer when there is room", async ({ page }) => {
  await signIn(page);
  await page.goto("/");
  const composer = page.getByLabel("Ask NOVA");
  await composer.fill("/pr");
  const menu = page.getByRole("listbox", { name: "Skills" });
  await expect(menu.getByRole("option").first()).toBeVisible();
  const box = (await menu.boundingBox())!;
  const viewport = page.viewportSize()!;
  expect(box.y).toBeGreaterThanOrEqual(0);
  expect(box.y + box.height).toBeLessThanOrEqual(viewport.height);
  await composer.press("Enter");
  await expect(composer).toHaveValue(/^\/\S+ $/);
});

test("execute-with-approval: NOVA's edit opens the approval dialog with the real diff", async ({ page }) => {
  await signIn(page, true, "execute_with_approval");
  await page.goto("/");
  await ask(page, "/prd Audit log export for compliance teams, filtered by project and date");
  await expect(page.getByLabel("Artifact title")).toBeVisible();
  await ask(page, "Rewrite the success metrics to be measurable");

  const dialog = page.getByRole("dialog");
  await expect(dialog.getByRole("heading", { name: /Apply changes to/ })).toBeVisible({ timeout: 30_000 });
  for (const heading of ["What will happen", "Impact", "Preview of changes", "Quality check"]) {
    await expect(dialog.getByRole("heading", { name: heading })).toBeVisible();
  }
  await expect(dialog.getByText(/Version 2 of .* becomes the current version/)).toBeVisible();
  await expect(dialog.getByRole("cell", { name: "Success metrics" }).first()).toBeVisible();
  await dialog.getByRole("button", { name: "Approve all" }).click();
  await expect(dialog).toBeHidden();
  await expect(page.getByText("approved", { exact: true })).toBeVisible({ timeout: 30_000 });
});
