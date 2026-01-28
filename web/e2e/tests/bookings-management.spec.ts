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

    const dateInput = page.getByTestId('bookings-date-input');
    await expect(dateInput).toBeVisible();

    // Set a specific date
    const today = new Date().toISOString().split('T')[0];
    await dateInput.fill(today);
    await expect(dateInput).toHaveValue(today);
  });

  test('bookings refresh button is functional', async ({ page }) => {
    await page.goto('/admin');

    await expect(page.getByTestId('admin-shell-ready')).toBeVisible();

    const refreshButton = page.getByTestId('bookings-refresh-btn');
    await expect(refreshButton).toBeVisible();
    await expect(refreshButton).toBeEnabled();

    // Click refresh button
    await refreshButton.click();

    // Table should still be visible after refresh
    await expect(page.getByTestId('bookings-table')).toBeVisible();
  });

  test('bookings table has expected columns', async ({ page }) => {
    await page.goto('/admin');

    await expect(page.getByTestId('admin-shell-ready')).toBeVisible();
    await expect(page.getByTestId('bookings-table')).toBeVisible();

    // Check for expected column headers
    const table = page.getByTestId('bookings-table');
    await expect(table.getByRole('columnheader', { name: 'When' })).toBeVisible();
    await expect(table.getByRole('columnheader', { name: 'Status' })).toBeVisible();
    await expect(table.getByRole('columnheader', { name: 'Lead' })).toBeVisible();
    await expect(table.getByRole('columnheader', { name: 'Duration' })).toBeVisible();
    await expect(table.getByRole('columnheader', { name: 'Actions' })).toBeVisible();
  });

  test('week view is displayed', async ({ page }) => {
    await page.goto('/admin');

    await expect(page.getByTestId('admin-shell-ready')).toBeVisible();
    await expect(page.getByTestId('admin-bookings-section')).toBeVisible();

    // Week view heading should be visible
    await expect(page.getByRole('heading', { name: 'Week view' })).toBeVisible();
  });
});
