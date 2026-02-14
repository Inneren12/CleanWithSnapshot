import { expect, test, type Page } from '@playwright/test';

import {
  defaultAdminCredentials,
  seedAdminStorage,
  verifyAdminCredentials,
} from './helpers/adminAuth';

const waitForBookingsReady = async (page: Page) => {
  const refreshButton = page.getByTestId('bookings-refresh-btn');
  await expect(refreshButton).toBeVisible({ timeout: 30_000 });
  await expect(refreshButton).not.toHaveText(/Loading/i, { timeout: 30_000 });
  await expect(refreshButton).toBeEnabled({ timeout: 30_000 });
};

test.describe('Bookings management', () => {
  test.beforeEach(async ({ page, request }) => {
    page.on('console', (msg) => {
      console.log(`[BROWSER][${msg.type()}] ${msg.text()}`);
    });
    page.on('pageerror', (err) => {
      console.log(`[BROWSER][ERROR] ${err.message}`);
    });
    page.on('response', (response) => {
      if (response.status() < 400) {
        return;
      }
      const url = response.url();
      if (url.includes('/v1/admin/')) {
        const reason = response.headers()['x-admin-auth-fail-reason'];
        console.log(
          '[E2E][API FAIL]',
          response.status(),
          url,
          reason ? `reason=${reason}` : ''
        );
      }
    });
    const admin = defaultAdminCredentials();
    await verifyAdminCredentials(request, admin);
    await seedAdminStorage(page, admin);
  });

  test('bookings section loads on admin dashboard', async ({ page }) => {
    await page.goto('/admin');

    await expect(page.getByTestId('admin-shell-ready')).toBeVisible();
    await expect(page.getByTestId('admin-bookings-section')).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Bookings' })).toBeVisible();
  });

  test('bookings table is displayed', async ({ page }) => {
    await page.goto('/admin');

    await expect(page.getByTestId('admin-shell-ready')).toBeVisible();
    await expect(page.getByTestId('bookings-table')).toBeVisible();
  });

  test('bookings date filter is functional', async ({ page }) => {
    await page.goto('/admin');

    await expect(page.getByTestId('admin-shell-ready')).toBeVisible();
    // Ensure no error page takeover
    await expect(page.locator('html#__next_error__')).toHaveCount(0);

    // Wait for stable controls wrapper
    await expect(page.getByTestId('bookings-controls')).toBeVisible();
    await waitForBookingsReady(page);

    const dateInput = page.getByTestId('bookings-date-input');
    await expect(dateInput).toBeVisible({ timeout: 30_000 });
    await expect(dateInput).toBeEnabled({ timeout: 30_000 });
    const applyButton = page.getByTestId('bookings-date-apply');
    await expect(applyButton).toBeVisible({ timeout: 30_000 });
    await expect(applyButton).toBeEnabled({ timeout: 30_000 });

    // Set a specific date
    const today = new Date().toISOString().split('T')[0];
    const waitForBookings = page.waitForResponse((response) => {
      return (
        response.request().method() === 'GET' &&
        response.url().includes('/v1/admin/bookings?from=') &&
        response.url().includes(`from=${today}`) &&
        response.ok()
      );
    });
    await dateInput.fill(today);
    await applyButton.click();
    await waitForBookings;
    await expect(dateInput).toHaveValue(today);
    await expect(page.getByTestId('bookings-table')).toBeVisible({ timeout: 30_000 });
  });

  test('bookings refresh button is functional', async ({ page }) => {
    await page.goto('/admin');

    await expect(page.getByTestId('admin-shell-ready')).toBeVisible();
    // Ensure no error page takeover
    await expect(page.locator('html#__next_error__')).toHaveCount(0);

    // Wait for stable controls wrapper
    await expect(page.getByTestId('bookings-controls')).toBeVisible();
    await waitForBookingsReady(page);

    const refreshButton = page.getByTestId('bookings-refresh-btn');
    await expect(refreshButton).toBeVisible({ timeout: 30_000 });
    await expect(refreshButton).toBeEnabled({ timeout: 30_000 });
    await expect(page.getByTestId('bookings-table')).toBeVisible({ timeout: 30_000 });

    // Click refresh button
    const waitForBookings = page.waitForResponse((response) => {
      return (
        response.request().method() === 'GET' &&
        response.url().includes('/v1/admin/bookings?from=') &&
        response.ok()
      );
    });
    await refreshButton.click();
    await waitForBookings;

    // Ensure no error page takeover after click
    await expect(page.locator('html#__next_error__')).toHaveCount(0);

    // Table should still be visible after refresh
    await expect(page.getByTestId('bookings-table')).toBeVisible({ timeout: 30_000 });
  });

  test('bookings table has expected columns', async ({ page }) => {
    await page.goto('/admin');

    await expect(page.getByTestId('admin-shell-ready')).toBeVisible();
    // Ensure no error page takeover
    await expect(page.locator('html#__next_error__')).toHaveCount(0);

    // Wait for stable controls wrapper first
    await expect(page.getByTestId('bookings-controls')).toBeVisible();
    await waitForBookingsReady(page);
    await expect(page.getByTestId('bookings-table')).toBeVisible();

    const refreshButton = page.getByTestId('bookings-refresh-btn');
    await expect(refreshButton).toBeVisible({ timeout: 30_000 });
    await expect(refreshButton).toBeEnabled({ timeout: 30_000 });
    const waitForBookings = page.waitForResponse((response) => {
      return (
        response.request().method() === 'GET' &&
        response.url().includes('/v1/admin/bookings?from=') &&
        response.ok()
      );
    });
    await refreshButton.click();
    await waitForBookings;

    // Check for expected column headers
    const columns = page.getByTestId('bookings-columns');
    await expect(columns.getByRole('columnheader', { name: 'When' })).toBeVisible();
    await expect(columns.getByRole('columnheader', { name: 'Status' })).toBeVisible();
    await expect(columns.getByRole('columnheader', { name: 'Lead' })).toBeVisible();
    await expect(columns.getByRole('columnheader', { name: 'Duration' })).toBeVisible();
    await expect(columns.getByRole('columnheader', { name: 'Actions' })).toBeVisible();
  });

  test('week view is displayed', async ({ page }) => {
    await page.goto('/admin');

    await expect(page.getByTestId('admin-shell-ready')).toBeVisible();
    await expect(page.getByTestId('admin-bookings-section')).toBeVisible();

    // Week view heading should be visible
    await expect(page.getByTestId('bookings-week-view')).toBeVisible();
  });
});
