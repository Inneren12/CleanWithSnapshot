import { expect, test } from '@playwright/test';

import {
  defaultAdminCredentials,
  seedAdminStorage,
  verifyAdminCredentials,
} from './helpers/adminAuth';

test.describe('Bookings management', () => {
  test.beforeEach(async ({ page, request }) => {
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

    const dateInput = page.getByTestId('bookings-date-input');
    await expect(dateInput).toBeVisible();
    await expect(dateInput).toBeEnabled();
    const applyButton = page.getByTestId('bookings-date-apply');
    await expect(applyButton).toBeVisible();
    await expect(applyButton).toBeEnabled();

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
    await expect(page.getByTestId('bookings-table')).toBeVisible();
  });

  test('bookings refresh button is functional', async ({ page }) => {
    await page.goto('/admin');

    await expect(page.getByTestId('admin-shell-ready')).toBeVisible();
    // Ensure no error page takeover
    await expect(page.locator('html#__next_error__')).toHaveCount(0);

    // Wait for stable controls wrapper
    await expect(page.getByTestId('bookings-controls')).toBeVisible();

    const refreshButton = page.getByTestId('bookings-refresh-btn');
    await expect(refreshButton).toBeVisible();
    await expect(refreshButton).toBeEnabled();
    await expect(refreshButton).not.toHaveText(/Loading/i);
    await expect(page.getByTestId('bookings-table')).toBeVisible();

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
    await expect(page.getByTestId('bookings-table')).toBeVisible();
  });

  test('bookings table has expected columns', async ({ page }) => {
    await page.goto('/admin');

    await expect(page.getByTestId('admin-shell-ready')).toBeVisible();
    // Ensure no error page takeover
    await expect(page.locator('html#__next_error__')).toHaveCount(0);

    // Wait for stable controls wrapper first
    await expect(page.getByTestId('bookings-controls')).toBeVisible();
    await expect(page.getByTestId('bookings-table')).toBeVisible();

    const refreshButton = page.getByTestId('bookings-refresh-btn');
    await expect(refreshButton).toBeVisible();
    await expect(refreshButton).toBeEnabled();
    await expect(refreshButton).not.toHaveText(/Loading/i);
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
