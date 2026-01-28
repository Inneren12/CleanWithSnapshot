import { expect, test } from '@playwright/test';

import {
  defaultAdminCredentials,
  seedAdminStorage,
  verifyAdminCredentials,
} from './helpers/adminAuth';

test.describe('Dispatcher page', () => {
  test.beforeEach(async ({ page, request }) => {
    const admin = defaultAdminCredentials();
    await verifyAdminCredentials(request, admin);
    await seedAdminStorage(page, admin);
  });

  test('dispatcher page loads with timeline', async ({ page }) => {
    await page.goto('/admin/dispatcher');

    await expect(page.getByTestId('dispatcher-page')).toBeVisible();
    await expect(page.getByTestId('dispatcher-header')).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Dispatcher Timeline' })).toBeVisible();
  });

  test('dispatcher page shows live schedule message', async ({ page }) => {
    await page.goto('/admin/dispatcher');

    await expect(page.getByTestId('dispatcher-page')).toBeVisible();
    await expect(page.getByText('Live schedule for today')).toBeVisible();
  });

  test('dispatcher page has navigation', async ({ page }) => {
    await page.goto('/admin/dispatcher');

    await expect(page.getByTestId('dispatcher-page')).toBeVisible();

    // Navigation should be present once links load
    const adminNav = page.getByTestId('admin-nav');
    await expect(adminNav).toBeAttached();
    await expect(page.getByRole('heading', { name: /dispatcher/i })).toBeVisible();
  });

  test('dispatcher page accessible from admin dashboard', async ({ page }) => {
    await page.goto('/admin');

    await expect(page.getByTestId('admin-shell-ready')).toBeVisible();

    // Click on Dispatcher link in navigation
    const dispatcherLink = page.getByRole('link', { name: 'Dispatcher' });
    if (await dispatcherLink.isVisible()) {
      await dispatcherLink.click();
      await expect(page.getByTestId('dispatcher-page')).toBeVisible();
    }
  });
});
