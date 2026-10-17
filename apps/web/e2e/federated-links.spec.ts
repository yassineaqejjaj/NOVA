import { expect, type Page, test } from "@playwright/test";

// Settings → Links in token exchange mode (NOV-114). The API is the real one running in the default `linked_session` mode, so the
// federated payload is served by a route handler: this checks the screen (labels EN/FR, states, actions, no secret), not the IdP.

const SUB = "5b1d0000…";
const TOKEN_LIKE = ["eyJ", "refresh-", "Bearer "];

type Status = "ok" | "expiring" | "expired" | "revoked" | "degraded" | "unlinked" | "not_configured";

function link(service: "orbit" | "forge", status: Status, extra: Record<string, unknown> = {}) {
  const linked = !["unlinked", "not_configured"].includes(status);
  return {
    service,
    status,
    linked,
    revoked_reason: status === "revoked" ? "user" : null,
    identity: { sub: linked ? SUB : null, email: "alice@example.test", issuer: "https://idp.orion.test/realms/orion", amr: ["pwd", "mfa"], act: null },
    project: { orion_project_id: "0a0b0c0d-0000-4000-8000-000000000106", alias: "atlas", workspace_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa" },
    expiry: { expires_at: "2026-10-16T12:05:00+00:00", remaining_seconds: 240, session_expires_at: "2026-10-16T20:00:00+00:00", renewal: "on_demand" },
    scope: { scopes: ["orion:context.read"], roles: ["admin"], clearance: { local: 2, cap: 1, effective: 1, reason: "capped_by_token" } },
    last_exchange: { at: "2026-10-16T12:00:00+00:00", status: "ok", exchange_ms: 42, consecutive_errors: status === "degraded" ? 2 : 0, last_error: status === "degraded" ? "audience_refused" : null, last_error_at: null },
    roundtrip: { at: "2026-10-16T12:00:05+00:00", operation: "search", status: "ok", latency_ms: 120 },
    call_errors: 0,
    actions: status === "not_configured" ? [] : service === "orbit" ? ["reconnect", "revoke", "test"] : ["reconnect", "revoke"],
    ...extra,
  };
}

async function signIn(page: Page, lang?: "en" | "fr", admin = false) {
  const email = `pm-${Date.now()}-${Math.round(Math.random() * 1e6)}@company.test`;
  await page.request.post("/api/v1/auth/dev-login", { data: { email, name: "Yassine", title: "Head of AI" } });
  await page.request.post("/api/v1/me/onboarding", { data: { title: "Head of AI", default_autonomy: "assist", ...(lang ? { language: lang } : {}) } });
  return admin;
}

async function mockLinks(page: Page, orbit: Status, forge: Status = "unlinked", workspace = false) {
  const calls = { revoked: [] as string[], tested: [] as string[] };
  await page.route("**/api/v1/me/links", async (route) => {
    // A static base (not route.fetch()): a refetch that lands while the test ends would race with the disposal of the response
    const base = { orbit: { linked: false, mode: "none", status: "unlinked", agent_keys: [] }, forge: null };
    await route.fulfill({
      json: { ...base, federated: { mode: "token_exchange", expiry_warning_seconds: 60, services: { orbit: link("orbit", orbit), forge: link("forge", forge) } } },
    });
  });
  await page.route("**/api/v1/me/links/*/test", async (route) => {
    calls.tested.push(new URL(route.request().url()).pathname);
    await route.fulfill({ json: { result: "ok", link: link("orbit", "ok") } });
  });
  await page.route("**/api/v1/me/links/*", async (route) => {
    if (route.request().method() === "DELETE") {
      calls.revoked.push(new URL(route.request().url()).pathname);
      await route.fulfill({ status: 204, body: "" });
    } else await route.fallback();
  });
  if (workspace) {
    await page.route("**/api/v1/admin/links", (route) =>
      route.fulfill({
        json: {
          mode: "token_exchange",
          members: [
            { user_id: "u1", name: "Alice Example", email: "a***@example.test", services: { orbit: { status: "ok", last_error: null, consecutive_errors: 0, expires_at: null, roundtrip: null }, forge: { status: "unlinked", last_error: null, consecutive_errors: 0, expires_at: null, roundtrip: null } } },
            { user_id: "u2", name: "Bob Example", email: "b***@example.test", services: { orbit: { status: "degraded", last_error: "audience_refused", consecutive_errors: 3, expires_at: null, roundtrip: null }, forge: { status: "revoked", last_error: null, consecutive_errors: 0, expires_at: null, roundtrip: null } } },
          ],
        },
      }),
    );
  }
  return calls;
}

test("federated links: who acts, the target project, expiry, scope and the last round trip, with no secret", async ({ page }) => {
  await signIn(page, "en");
  await mockLinks(page, "ok");
  await page.goto("/settings#links");
  const orbit = page.getByTestId("federated-orbit");
  await expect(orbit).toHaveAttribute("data-status", "ok");
  await expect(orbit).toContainText("Healthy");
  await expect(page.getByTestId("federated-identity").first()).toContainText(`you (${SUB})`);
  await expect(page.getByTestId("federated-amr").first()).toHaveText("pwd, mfa");
  await expect(page.getByTestId("federated-act").first()).toHaveText("no one (direct)");
  await expect(page.getByTestId("federated-project").first()).toContainText("atlas");
  await expect(page.getByTestId("federated-expiry").first()).toContainText("240 s left");
  await expect(page.getByTestId("federated-expiry").first()).toContainText("never stored");
  await expect(page.getByTestId("federated-scope").first()).toHaveText("orion:context.read");
  await expect(page.getByTestId("federated-clearance").first()).toContainText("C1");
  await expect(page.getByTestId("federated-clearance").first()).toContainText("capped by your organisation: C1 (yours is C2)");
  await expect(page.getByTestId("federated-roundtrip").first()).toContainText("search · ok · 120 ms");
  const text = (await page.getByTestId("links-card").innerText()) ?? "";
  for (const secret of TOKEN_LIKE) expect(text).not.toContain(secret);
  await expect(page.getByTestId("link-orbit")).toHaveCount(0); // replaced by the federated view in this mode
});

test("federated links: every state has its own label and message, in English and in French", async ({ page }) => {
  await signIn(page, "en");
  const states: [Status, string, string][] = [
    ["ok", "Healthy", "En bonne santé"],
    ["expiring", "Expires soon", "Expire bientôt"],
    ["expired", "Expired", "Expiré"],
    ["revoked", "Revoked", "Révoqué"],
    ["degraded", "Degraded", "Dégradé"],
    ["unlinked", "Not linked", "Non lié"],
    ["not_configured", "Not configured", "Non configuré"],
  ];
  for (const [status, en] of states) {
    await page.unrouteAll({ behavior: "ignoreErrors" });
    await mockLinks(page, status, status);
    await page.goto("/settings#links");
    await page.reload(); // same page, new hash: reload so the (re-mocked) links are fetched again
    await expect(page.getByTestId("federated-orbit")).toHaveAttribute("data-status", status);
    await expect(page.getByTestId("federated-orbit")).toContainText(en);
    if (["expired", "revoked", "degraded", "unlinked", "not_configured"].includes(status)) await expect(page.getByTestId("federated-hint").first()).toBeVisible();
    else await expect(page.getByTestId("federated-hint")).toHaveCount(0);
  }
  await page.request.patch("/api/v1/me/preferences", { data: { language: "fr" } });
  for (const [status, , fr] of states) {
    await page.unrouteAll({ behavior: "ignoreErrors" });
    await mockLinks(page, status, status);
    await page.goto("/settings#links");
    await page.reload();
    await expect(page.getByTestId("federated-orbit")).toContainText(fr);
  }
  await page.unrouteAll({ behavior: "ignoreErrors" });
  await mockLinks(page, "ok");
  await page.goto("/settings#links");
  await page.reload();
  await expect(page.getByTestId("federated-clearance").first()).toContainText("plafonnée par votre organisation : C1 (la vôtre est C2)");
  await expect(page.getByTestId("federated-expiry").first()).toContainText("240 s restantes");
  await expect(page.getByTestId("federated-orbit").getByRole("button", { name: "Tester le lien" })).toBeVisible();
});

test("federated links: reconnect, revoke and test the link", async ({ page }) => {
  await signIn(page, "en");
  const calls = await mockLinks(page, "ok");
  await page.goto("/settings#links");
  const orbit = page.getByTestId("federated-orbit");
  await expect(orbit.getByTestId("federated-reconnect")).toBeVisible();
  await orbit.getByTestId("federated-test").click();
  await expect(orbit.getByTestId("federated-test-result")).toContainText("Link works");
  expect(calls.tested).toEqual(["/api/v1/me/links/orbit/test"]);
  await expect(page.getByTestId("federated-forge").getByTestId("federated-test")).toHaveCount(0); // nothing to test per user for FORGE
  await orbit.getByTestId("federated-revoke").click();
  await expect.poll(() => calls.revoked).toEqual(["/api/v1/me/links/orbit"]);
});

test("federated links: the screen is read only for a member (no workspace table) and an unlinked member gets no actions that act", async ({ page }) => {
  await signIn(page, "en");
  await mockLinks(page, "not_configured", "not_configured", true);
  await page.goto("/settings#links");
  await expect(page.getByTestId("federated-orbit")).toHaveAttribute("data-status", "not_configured"); // rendered before we look
  await expect(page.getByTestId("workspace-links-section")).toHaveCount(0); // administrators only
  await expect(page.getByTestId("federated-orbit").getByTestId("federated-test")).toHaveCount(0);
  await expect(page.getByTestId("federated-orbit").getByTestId("federated-revoke")).toHaveCount(0);
});

test("default mode: Settings → Links has no federated view and is the screen it always was", async ({ page }) => {
  await signIn(page, "en");
  await page.goto("/settings#links");
  await expect(page.getByTestId("link-orbit")).toBeVisible();
  await expect(page.getByTestId("federated-orbit")).toHaveCount(0);
  await expect(page.getByTestId("federated-forge")).toHaveCount(0);
});
