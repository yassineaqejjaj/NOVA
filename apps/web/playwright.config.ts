import { defineConfig, devices } from "@playwright/test";

// E2E: real NOVA API + web, with test doubles for the inference server and ORBIT (tests/support).
const root = "../..";
const api = {
  NOVA_ENV: "test",
  NOVA_AUTH_MODE: "dev",
  NOVA_DATABASE_URL: "sqlite+aiosqlite:////tmp/nova-e2e.db",
  NOVA_CELERY_TASK_ALWAYS_EAGER: "true",
  NOVA_INLINE_EXECUTION: "background",
  NOVA_LLM_PROVIDER: "openai_compatible",
  NOVA_LLM_BASE_URL: "http://127.0.0.1:8391/v1",
  NOVA_LLM_MODEL: "fake-model",
  NOVA_ORBIT_BASE_URL: "http://127.0.0.1:8392",
  NOVA_FORGE_API_KEY: "",
  PYTHONPATH: ".:apps/api:services/worker",
};

export default defineConfig({
  testDir: "./e2e",
  timeout: 90_000,
  expect: { timeout: 20_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: { baseURL: "http://127.0.0.1:3293", trace: "retain-on-failure" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } } }],
  webServer: [
    { command: "uv run uvicorn tests.support.fake_llm_server:app --port 8391", cwd: root, url: "http://127.0.0.1:8391/docs", reuseExistingServer: true },
    { command: "uv run uvicorn tests.support.fake_orbit_server:app --port 8392", cwd: root, url: "http://127.0.0.1:8392/docs", reuseExistingServer: true },
    { command: "uv run python tests/support/e2e_api.py", cwd: root, url: "http://127.0.0.1:8293/health", env: api, reuseExistingServer: false, timeout: 60_000 },
    {
      command: "npx next build && npx next start -p 3293",
      url: "http://127.0.0.1:3293/login",
      env: { NOVA_API_URL: "http://127.0.0.1:8293", NEXT_DIST_DIR: ".next-e2e" },
      reuseExistingServer: false,
      timeout: 300_000,
    },
  ],
});
