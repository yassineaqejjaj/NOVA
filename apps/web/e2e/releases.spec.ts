import { expect, type Page, test } from "@playwright/test";

const now = new Date().toISOString();

const release = (over: Record<string, unknown>) => ({
  id: "11111111-1111-4111-8111-111111111111",
  agent: "product",
  label: "product v3",
  status: "awaiting_approval",
  canary_percent: 10,
  policy_id: "22222222-2222-4222-8222-222222222222",
  baseline_policy_id: "33333333-3333-4333-8333-333333333333",
  evidence: { delta: 6.5 },
  reason: "Échecs 5% contre 6% pour les autres. En attente d'approbation.",
  decided_by: null,
  created_at: now,
  canary_started_at: now,
  decided_at: null,
  canary: { runs: 24, failed: 1, failure_rate: 0.0417 },
  control: { runs: 180, failed: 11, failure_rate: 0.0611 },
  min_runs: 20,
  ...over,
});

const agents = ["product", "project", "design", "engineering"].map((agent) => ({
  agent,
  name: agent,
  skills_count: 3,
  active: null,
  last_cycle: null,
  training: false,
}));

async function mock(page: Page, releases: unknown[], canManage = true) {
  const approved: string[] = [];
  await page.route("**/api/v1/training", (route) =>
    route.fulfill({ json: { missing: [], auto_promote: true, release: { canary_percent: 10, approval: "full" }, interval_days: 0, repetitions: 1, forge_url: "http://forge", can_manage: canManage, agents } }),
  );
  await page.route("**/api/v1/training/agents/product", (route) =>
    route.fulfill({ json: { agent: "product", name: "Product", can_manage: canManage, active: null, skills: [], policies: [], cycles: [] } }),
  );
  await page.route("**/api/v1/releases", (route) => route.fulfill({ json: { can_manage: canManage, releases } }));
  await page.route("**/api/v1/releases/*/approve", (route) => {
    approved.push(route.request().url());
    return route.fulfill({ json: release({ status: "active" }) });
  });
  return approved;
}

async function signIn(page: Page) {
  const email = `admin-${Date.now()}-${Math.round(Math.random() * 1e6)}@company.test`;
  await page.request.post("/api/v1/auth/dev-login", { data: { email, name: "Yassine", title: "Head of AI" } });
  await page.request.post("/api/v1/me/onboarding", { data: { title: "Head of AI", default_autonomy: "assist" } });
}

test("a healthy canary shows its comparison and an administrator approves it", async ({ page }) => {
  const approved = await mock(page, [
    release({}),
    release({ id: "44444444-4444-4444-8444-444444444444", label: "product v2", status: "rolled_back", reason: "Échecs 50% contre 5% pour les autres.", decided_by: "system", decided_at: now }),
    release({
      id: "55555555-5555-4555-8555-555555555555",
      label: "product v1",
      status: "active",
      reason: "Approuvée par un administrateur.",
      decided_by: "66666666-6666-4666-8666-666666666666",
      decided_at: now,
      evidence: { delta: 3.2, health: { status: "healthy", reason: "ok", alerts: [], checked_at: now } },
    }),
  ]);
  await signIn(page);
  await page.goto("/team/training?agent=product");

  const section = page.getByRole("region", { name: "Releases" });
  await expect(section).toBeVisible();
  await expect(section.getByText("product v3")).toBeVisible();
  await expect(section.getByText("Awaiting approval")).toBeVisible();
  await expect(section.getByText("10% of users")).toBeVisible();
  await expect(section.getByText("4% failed (1/24)")).toBeVisible();
  await expect(section.getByText("6% failed (11/180)")).toBeVisible();
  await expect(section.getByText("FORGE gain +6.5 pts")).toBeVisible();
  // History
  await expect(section.getByText("Rolled back")).toBeVisible();
  await expect(section.getByText("Échecs 50% contre 5% pour les autres.")).toBeVisible();
  await expect(section.getByText("FORGE watch · no degradation on real traffic")).toBeVisible();

  page.once("dialog", (dialog) => dialog.accept());
  await section.getByRole("button", { name: "Approve for everyone" }).click();
  await expect.poll(() => approved.length).toBe(1);
  expect(approved[0]).toContain("/api/v1/releases/11111111-1111-4111-8111-111111111111/approve");
});

test("a running canary shows its progress; non-administrators see no decision button", async ({ page }) => {
  await mock(page, [release({ status: "canary", canary: { runs: 5, failed: 0, failure_rate: 0 }, control: { runs: 0, failed: 0, failure_rate: 0 } })], false);
  await signIn(page);
  await page.goto("/team/training?agent=product");
  const section = page.getByRole("region", { name: "Releases" });
  await expect(section.getByText("5/20 runs observed")).toBeVisible();
  await expect(section.getByText("No run yet")).toBeVisible();
  await expect(section.getByRole("button", { name: /Approve|Roll back|Compare now/ })).toHaveCount(0);
});

test("an agent without any release says so", async ({ page }) => {
  await mock(page, []);
  await signIn(page);
  await page.goto("/team/training?agent=product");
  await expect(page.getByRole("region", { name: "Releases" }).getByText("No release yet.")).toBeVisible();
});
