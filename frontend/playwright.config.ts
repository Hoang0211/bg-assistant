import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  reporter: "list",
  use: { baseURL: "http://localhost:3000", trace: "retain-on-failure" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  // Starts the backend and frontend if they aren't already running; the database must be up in Docker.
  webServer: [
    {
      command: "uv run uvicorn app.main:app --port 8000 --loop asyncio:SelectorEventLoop",
      cwd: "../backend",
      url: "http://localhost:8000/api/health",
      reuseExistingServer: true,
    },
    {
      command: "npm run dev",
      url: "http://localhost:3000",
      reuseExistingServer: true,
    },
  ],
});
