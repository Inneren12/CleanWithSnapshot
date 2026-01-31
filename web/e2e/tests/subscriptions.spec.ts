import crypto from "crypto";
import { expect, test } from "@playwright/test";

import {
  defaultAdminCredentials,
  seedAdminStorage,
  verifyAdminCredentials,
} from "./helpers/adminAuth";

async function requireOk<ResponseType>(response, label: string): Promise<ResponseType> {
  if (response.ok()) {
    return (await response.json()) as ResponseType;
  }
  const body = await response.text();
  console.error(`[e2e] ${label} failed (${response.status()}): ${body}`);
  throw new Error(`${label} failed with status ${response.status()}`);
}

test.describe("Subscriptions lifecycle", () => {
  test("create, pause, and resume subscription", async ({ page, request }, testInfo) => {
    const admin = defaultAdminCredentials();
    await verifyAdminCredentials(request, admin);
    await seedAdminStorage(page, admin);

    const uniqueSuffix = `${testInfo.workerIndex}-${testInfo.parallelIndex}-${crypto.randomUUID().slice(0, 8)}`;
    const clientEmail = `e2e-subscription-${uniqueSuffix}@example.com`;
    const serviceType = `E2E Standard ${uniqueSuffix}`;
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

    const createResponsePromise = page.waitForResponse((response) => {
      return response.url().includes("/v1/admin/subscriptions") && response.request().method() === "POST";
    });

    await page.getByTestId("subscription-create-btn").click();

    const createResponse = await createResponsePromise;
    const created = await requireOk<{ subscription_id: string }>(createResponse, "create subscription");
    const subscriptionId = created.subscription_id;

    const statusLabel = page.getByTestId(`subscription-status-${subscriptionId}`);
    await expect(statusLabel).toHaveText("ACTIVE");

    await page.getByTestId(`subscription-pause-btn-${subscriptionId}`).click();

    const pauseResponsePromise = page.waitForResponse((response) => {
      return response.url().includes(`/v1/admin/subscriptions/${subscriptionId}`) && response.request().method() === "PATCH";
    });

    await page.getByTestId(`subscription-confirm-pause-btn-${subscriptionId}`).click();
    const pauseResponse = await pauseResponsePromise;
    await requireOk(pauseResponse, "pause subscription");

    await expect(statusLabel).toHaveText("PAUSED");

    await page.getByTestId(`subscription-resume-btn-${subscriptionId}`).click();

    const resumeResponsePromise = page.waitForResponse((response) => {
      return response.url().includes(`/v1/admin/subscriptions/${subscriptionId}`) && response.request().method() === "PATCH";
    });

    await page.getByTestId(`subscription-confirm-resume-btn-${subscriptionId}`).click();
    const resumeResponse = await resumeResponsePromise;
    await requireOk(resumeResponse, "resume subscription");

    await expect(statusLabel).toHaveText("ACTIVE");
  });
});
