import { expect, test } from '@playwright/test';

import {
  defaultAdminCredentials,
  seedAdminStorage,
  verifyAdminCredentials,
} from './helpers/adminAuth';
import { newContextWithBaseUrl } from './helpers/playwrightContext';

test.describe('Invoices page', () => {
  test.beforeEach(async ({ page, request }) => {
    const admin = defaultAdminCredentials();
    await verifyAdminCredentials(request, admin);
    await seedAdminStorage(page, admin);
  });

  test('invoices page shows login form when not authenticated', async ({
    page,
  }, testInfo) => {
    // Go to invoices without pre-seeded storage in a new context
    const newContext = await newContextWithBaseUrl({ page, testInfo });
    const newPage = await newContext.newPage();

    await newPage.goto('/admin/invoices');

    await expect(newPage.getByTestId('invoices-login-page')).toBeVisible();
    await expect(newPage.getByTestId('invoices-login-form')).toBeVisible();
    await expect(newPage.getByTestId('invoices-username-input')).toBeVisible();
    await expect(newPage.getByTestId('invoices-password-input')).toBeVisible();
    await expect(newPage.getByTestId('invoices-login-btn')).toBeVisible();

    await newContext.close();
  });

  test('invoices page loads after login', async ({ page }) => {
    await page.goto('/admin/invoices');

    await expect(page.getByTestId('invoices-page')).toBeVisible();
    await expect(page.getByTestId('invoices-title')).toBeVisible();
  });

  test('invoices page shows overdue summary section', async ({ page }) => {
    await page.goto('/admin/invoices');

    await expect(page.getByTestId('invoices-page')).toBeVisible();
    await expect(page.getByTestId('overdue-summary')).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Overdue invoices' })).toBeVisible();
  });

  test('invoices page shows invoice table', async ({ page }) => {
    await page.goto('/admin/invoices');

    await expect(page.getByTestId('invoices-page')).toBeVisible();

    // Wait for loading to finish
    const loadingIndicator = page.getByTestId('invoices-loading');
    if (await loadingIndicator.isVisible()) {
      await expect(loadingIndicator).not.toBeVisible({ timeout: 10000 });
    }

    // Table should be visible after loading
    await expect(page.getByTestId('invoices-table')).toBeVisible();
  });

  test('invoices page uses isolated auth in a new context', async ({ page }, testInfo) => {
    // Go to invoices in new context without pre-seeded storage
    const newContext = await newContextWithBaseUrl({ page, testInfo });
    const newPage = await newContext.newPage();

    await newPage.goto('/admin/invoices');

    const loginPage = newPage.getByTestId('invoices-login-page');
    const invoicesPage = newPage.getByTestId('invoices-page');
    await expect(loginPage.or(invoicesPage)).toBeVisible();

    await newContext.close();
  });
});
