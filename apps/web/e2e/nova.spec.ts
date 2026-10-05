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
  for (let i = 0; i < 6; i++) await page.getByRole("button", { name: /Continue/ }).click(); // role → profile → … → autonomy → ORBIT
  await page.getByRole("button", { name: "Skip for now" }).click();
  await expect(page.getByText(/Your .* is ready\./)).toBeVisible();
  await page.getByRole("button", { name: "Start working" }).click();

  await expect(page.getByText(/, Yassine\./)).toBeVisible();
  await expect(page.getByRole("heading", { name: /Here's what matters/ })).toBeVisible();
  await expect(page.getByPlaceholder(/Ask NOVA anything/)).toBeVisible();
  await expect(page.getByLabel("NOVA status")).toContainText("Ready");
  await expect(page.getByText("ORBIT · Not linked")).toBeVisible();
  await expect(page.getByText("No evaluation yet")).toBeVisible();
  await page.getByRole("button", { name: "Prepare my next sprint" }).click();
  await expect(page.getByLabel("Ask NOVA")).toHaveValue(/^\/sprint-planning /);
  await page.getByLabel("Ask NOVA").fill("");
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
  await expect(page.getByRole("heading", { name: "Library" })).toBeVisible();
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

test.describe("landing (French browser)", () => {
  test.use({ locale: "fr-FR" });

  test("visitors see the landing page at /, with the demo CTA and sign-in", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("heading", { level: 1 })).toContainText("L’IA agentique");
    await expect(page.getByRole("link", { name: "Réserver une démo" }).first()).toHaveAttribute("href", /^mailto:/);
    await page.getByRole("button", { name: "English" }).click();
    await expect(page.getByRole("heading", { level: 1 })).toContainText("Agentic AI");
    await page.getByRole("link", { name: "Sign in" }).first().click();
    await expect(page).toHaveURL(/\/login/);

    await signIn(page);
    await page.goto("/");
    await expect(page.getByRole("heading", { name: /Here's what matters/ })).toBeVisible();
  });
});

test("Home is a command center: brief, continue, real results and the Timeline chain", async ({ page }) => {
  await signIn(page);
  await page.goto("/");
  await ask(page, "/prd Scheduled CSV exports of evaluation results for stakeholders");
  await expect(page.getByLabel("Artifact title")).toBeVisible();
  await page.goto("/");
  await expect(page.getByLabel("Your day")).toContainText("1result ready");
  await expect(page.getByRole("link", { name: /Continue where you left off/ })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Recent results" })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Timeline" })).toBeVisible();
  await page.goto("/activity");
  await expect(page.getByRole("heading", { name: "Timeline" })).toBeVisible();
  await expect(page.getByText("NOVA", { exact: true }).first()).toBeVisible();
});

test("Settings: switch the interface to French and pick an orb color (saved to the profile)", async ({ page }) => {
  await signIn(page);
  await page.goto("/settings");
  await page.getByRole("radio", { name: "Violet" }).click();
  await expect(page.getByRole("radio", { name: "Violet" })).toHaveAttribute("aria-checked", "true");
  await page.getByRole("radio", { name: "Français" }).click();
  await expect(page.getByRole("heading", { name: "Paramètres" })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Principal" }).getByRole("link", { name: "Accueil" })).toBeVisible();

  // Saved server-side: a fresh browser storage still gets French + violet from the profile.
  await page.evaluate(() => localStorage.clear());
  await page.goto("/");
  await expect(page.getByRole("heading", { name: /Voici l’essentiel/ })).toBeVisible();
  await expect(page.getByPlaceholder(/Demandez ce que vous voulez à NOVA/)).toBeVisible();
  const me = await page.evaluate(() => fetch("/api/v1/me").then((r) => r.json()));
  expect(me.preferences).toMatchObject({ language: "fr", orb_color: "violet" });

  await page.goto("/settings");
  await page.getByRole("radio", { name: "English" }).click();
  await expect(page.getByRole("heading", { name: "Settings" })).toBeVisible();
});

test("Sub-agents: NOVA delegates each step to the Design and Engineering agents, live; the profile drives Home", async ({ page }) => {
  await signIn(page);
  await page.request.patch("/api/v1/me/preferences", { data: { profile: "design" } });
  await page.goto("/");
  await expect(page.getByLabel("Suggested requests")).toContainText("Design agent");
  await expect(page.getByRole("button", { name: "Write the design brief for onboarding" })).toBeVisible();

  await ask(page, "Write the design brief and the technical design of the onboarding flow");
  await page.getByRole("button", { name: "Run workflow" }).click();
  const team = page.getByTestId("sub-agents");
  await expect(team).toContainText("orchestrating the sub-agents");
  await expect(team.locator('[data-agent="design"]')).toContainText("Design agent");
  await expect(team.locator('[data-agent="engineering"]')).toContainText("Engineering agent");
  await expect(team.locator('[data-agent="design"][data-status="done"]')).toBeVisible({ timeout: 45_000 });
  await expect(team.locator('[data-agent="engineering"][data-status="done"]')).toBeVisible({ timeout: 45_000 });
  await expect(team.getByText("2/2 steps")).toBeVisible();
  await expect(page.getByLabel("Artifact title")).toBeVisible();

  // The task keeps its team: Tasks shows who did what
  await page.goto("/work?tab=completed");
  await page.getByText("Write the design brief and the technical design of the onboarding flow").first().click();
  await expect(page.getByTestId("sub-agents").locator('[data-agent="engineering"]')).toBeVisible();

  // Settings: switching the profile changes the lead agent on Home; Skills can be filtered by agent
  await page.goto("/settings");
  await page.getByRole("radio", { name: /Engineering/ }).click();
  await expect(page.getByText("Profile updated.")).toBeVisible();
  await page.goto("/skills");
  await page.getByRole("radiogroup", { name: "Filter by agent" }).getByRole("radio", { name: /Engineering/ }).click();
  await expect(page.getByText("Technical Design", { exact: true })).toBeVisible();
  await expect(page.getByText("Status Report", { exact: true })).toHaveCount(0);
  await page.goto("/");
  await expect(page.getByLabel("Suggested requests")).toContainText("Engineering agent");
});

test("Voice: talk to NOVA from the orb — transcript sent as an autonomous request, answer spoken and captioned", async ({ page }) => {
  await signIn(page);
  const sent: Record<string, unknown>[] = [];
  page.on("request", (request) => {
    if (request.method() === "POST" && /\/api\/v1\/conversations\/[^/]+\/messages$/.test(request.url())) sent.push(request.postDataJSON());
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Talk with NOVA" }).first().click();

  const captions = page.getByTestId("voice-captions");
  await expect(captions).toContainText("What is a good north star metric", { timeout: 30_000 }); // from the fake microphone
  await expect(captions.getByText("NOVA", { exact: true }).last()).toBeVisible({ timeout: 45_000 }); // NOVA's spoken reply
  expect(sent[0]).toMatchObject({ autonomy: "execute_automatically" });
  await page.getByRole("button", { name: "Close" }).click();
  await expect(page.getByTestId("voice-captions")).toBeHidden();
});

test("Voice never reads C2/C3 answers aloud: it says the answer is on screen", async ({ page }) => {
  await signIn(page);
  await linkOrbit(page);
  const spoken: string[] = [];
  page.on("request", (request) => {
    if (request.method() === "POST" && request.url().endsWith("/api/v1/voice/speak")) spoken.push(String(request.postDataJSON()?.text ?? ""));
  });
  await page.goto("/");
  await page.getByLabel("Project").click();
  await page.getByRole("option", { name: "FORGE" }).click();
  await page.getByRole("button", { name: "Talk with NOVA" }).first().click();

  const captions = page.getByTestId("voice-captions");
  await expect(captions.getByText("Not read aloud")).toBeVisible({ timeout: 45_000 });
  await expect(captions).toContainText("contains confidential information");
  expect(spoken.every((text) => text === "On it." || text.includes("confidential information"))).toBeTruthy();
  await page.getByRole("button", { name: "Close" }).click();
});
