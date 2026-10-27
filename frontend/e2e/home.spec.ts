import { expect, test } from "@playwright/test";

test("home page shows the backend and database as up", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveTitle("Board Game Assistant");
  await expect(page.getByRole("status")).toHaveText("Backend and database are up.");
});
