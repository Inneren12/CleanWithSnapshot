import { expect, test } from "@playwright/test";

import {
  defaultAdminCredentials,
  seedAdminStorage,
  verifyAdminCredentials,
} from "./helpers/adminAuth";

test.describe("Subscriptions lifecycle", () => {
  test("create, pause, and resume subscription", async ({ page, request }, testInfo) => {
    const failedRequests: string[] = [];
    const consoleErrors: string[] = [];
    page.on("requestfailed", (req) => {
      failedRequests.push(`${req.method()} ${req.url()} - ${req.failure()?.errorText ?? "unknown error"}`);
    });
    page.on("console", (msg) => {
      if (msg.type() === "error") {
        consoleErrors.push(msg.text());
      }
    });

    try {
      const admin = defaultAdminCredentials();
      await verifyAdminCredentials(request, admin);
      await seedAdminStorage(page, admin);

      const suffix = `${testInfo.workerIndex}-${Date.now().toString().slice(-6)}`;
      const clientEmail = `e2e-subscription-${suffix}@example.com`;
      const serviceType = `E2E Standard ${suffix}`;
      const startDate = "2024-01-15";

      await page.goto("/admin/subscriptions");
      await expect(page.getByTestId("subscriptions-page")).toBeVisible();
      await expect(page.getByTestId("subscriptions-title")).toBeVisible();

      await page.getByTestId("subscription-client-email-input").fill(clientEmail);
      await page.getByTestId("subscription-client-name-input").fill("E2E Subscription Client");
      await page.getByTestId("subscription-frequency-select").selectOption("WEEKLY");
      await page.getByTestId("subscription-start-date-input").fill(startDate);
      await page.getByTestId("subscription-service-input").fill(serviceType);
      await page.getByTestId("subscription-price-input").fill("12000");

      await page.getByTestId("subscription-create-submit").click();
      await expect(page.getByTestId("subscription-create-success")).toBeVisible({ timeout: 30_000 });

      const row = page.getByRole("row", { name: new RegExp(serviceType) });
      await expect(row).toBeVisible({ timeout: 30_000 });

      const statusLabel = row.getByTestId("subscription-status");
      await expect(statusLabel).toHaveText("ACTIVE");

      await row.getByTestId("subscription-pause").click();
      await row.getByTestId("subscription-confirm-pause").click();
      await expect(statusLabel).toHaveText("PAUSED");

      await row.getByTestId("subscription-resume").click();
      await row.getByTestId("subscription-confirm-resume").click();
      await expect(statusLabel).toHaveText("ACTIVE");
    } catch (error) {
      if (failedRequests.length > 0) {
        console.log(`[e2e] Failed requests:\n${failedRequests.join("\n")}`);
      }
      if (consoleErrors.length > 0) {
        console.log(`[e2e] Console errors:\n${consoleErrors.join("\n")}`);
      }
      throw error;
    }
  });
});
