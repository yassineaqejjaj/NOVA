import { expect, test } from "@playwright/test";

test("Engineering: from an intent to a merged change, with the plan and the merge approved by the user", async ({ page }) => {
  const email = `dev-${Date.now()}-${Math.round(Math.random() * 1e6)}@company.test`;
  await page.request.post("/api/v1/auth/dev-login", { data: { email, name: "Yassine", title: "Engineer" } });
  await page.request.post("/api/v1/me/onboarding", { data: { title: "Engineer", default_autonomy: "assist" } });

  // Not connected yet: the page explains what to set up
  await page.goto("/engineering");
  await expect(page.getByTestId("eng-setup")).toContainText("GitHub");

  // Settings: GitHub (token tested against GitHub) and the user's own model
  await page.goto("/settings#github");
  await page.getByLabel("GitHub personal access token").fill("ghp_e2eTokenThatIsLongEnoughToPass0123456789");
  await page.getByRole("button", { name: "Connect", exact: true }).click();
  await expect(page.getByText("Connected as octo")).toBeVisible();
  await expect(page.getByLabel("API key", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Test and save" })).toBeDisabled(); // needs a key and the data-sharing acknowledgement

  // New run
  await page.goto("/engineering");
  await page.getByTestId("new-run").click();
  await page.getByLabel("Repository").click();
  await page.getByRole("option", { name: /o\/r/ }).click();
  await page.getByLabel("Describe the change").fill("Add a farewell function next to greet, with a test.");
  await page.getByRole("button", { name: "Start the run" }).click();

  // Guided: the run stops after the design and waits for the plan to be approved
  await expect(page).toHaveURL(/\/engineering\/[0-9a-f-]{36}/);
  await expect(page.getByTestId("gate")).toContainText("Approve the plan");
  await expect(page.locator('[data-stage="spec"]')).toHaveAttribute("data-status", "done");
  await expect(page.locator('[data-stage="implement"]')).toHaveAttribute("data-status", "pending");
  await page.locator('[data-stage="design"]').getByRole("button").click();
  await expect(page.locator('[data-stage="design"]').getByText("Planned changes")).toBeVisible();
  await page.getByLabel("Instructions for the implementation (optional)").fill("Keep it tiny");
  await page.getByTestId("approve").click();

  // Code, tests, PR, review and CI run on their own, then the merge needs approval
  await expect(page.getByTestId("gate")).toContainText("Merge the pull request");
  for (const stage of ["implement", "tests", "pull_request", "review", "ci"]) {
    await expect(page.locator(`[data-stage="${stage}"]`)).toHaveAttribute("data-status", "done");
  }
  await expect(page.getByRole("link", { name: "#1" })).toBeVisible();
  await page.getByTestId("approve").click();

  await expect(page.getByTestId("run-status")).toHaveAttribute("data-status", "completed");
  await expect(page.locator('[data-stage="merge"]')).toHaveAttribute("data-status", "done");
  await expect(page.getByTestId("release-card")).toBeVisible();
  await page.screenshot({ path: process.env.E2E_SHOT ?? "/tmp/nova-engineering.png", fullPage: true });

  // Listed on the Engineering page
  await page.goto("/engineering");
  await expect(page.getByTestId("run-row")).toHaveCount(1);
  await expect(page.getByTestId("run-row")).toContainText("Completed");

  // Evaluation: success rate, CI repairs and cost (tokens) of the runs
  await expect(page.getByTestId("p-success")).toContainText("100%");
  await expect(page.getByTestId("performance")).toContainText("CI repairs per run");
  await page.screenshot({ path: process.env.E2E_SHOT_LIST ?? "/tmp/nova-engineering-list.png", fullPage: true });
  await page.getByTestId("run-row").click();
  await expect(page.getByTestId("run-evaluation")).toContainText("CI green first time");
});
