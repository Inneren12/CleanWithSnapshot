import { expect, test } from '@playwright/test';

import {
  defaultAdminCredentials,
  seedAdminStorage,
  verifyAdminCredentials,
} from './helpers/adminAuth';

test.describe('Schedule page', () => {
  test.beforeEach(async ({ page, request }) => {
    const admin = defaultAdminCredentials();
    await verifyAdminCredentials(request, admin);
    await seedAdminStorage(page, admin);
  });

  test('schedule page loads with auth section', async ({ page }) => {
    await page.goto('/admin/schedule');

    await expect(page.getByTestId('schedule-page')).toBeVisible();
    await expect(page.getByTestId('schedule-auth-section')).toBeVisible();
    await expect(page.getByTestId('schedule-username-input')).toBeVisible();
    await expect(page.getByTestId('schedule-password-input')).toBeVisible();
    await expect(page.getByTestId('schedule-save-btn')).toBeVisible();
  });

  test('schedule page displays view tabs', async ({ page }) => {
    await page.goto('/admin/schedule');

    await expect(page.getByTestId('schedule-page')).toBeVisible();
    await expect(page.getByRole('tablist')).toBeVisible();

    // Check view tabs are present
    await expect(page.getByRole('tab', { name: 'Day' })).toBeVisible();
    await expect(page.getByRole('tab', { name: 'Week' })).toBeVisible();
    await expect(page.getByRole('tab', { name: 'Timeline' })).toBeVisible();
  });

  test('schedule page can switch between views', async ({ page }) => {
    await page.goto('/admin/schedule');

    await expect(page.getByTestId('schedule-page')).toBeVisible();
    await expect(page.getByRole('tablist')).toBeVisible();

    // Click on Week tab
    const weekTab = page.getByRole('tab', { name: 'Week' });
    await weekTab.click();

    // URL should update to include view parameter
    await expect(page).toHaveURL(/view=week/);

    // Click on Timeline tab
    const timelineTab = page.getByRole('tab', { name: 'Timeline' });
    await timelineTab.click();

    await expect(page).toHaveURL(/view=timeline/);
  });

  test('schedule credentials can be saved', async ({ page }) => {
    const admin = defaultAdminCredentials();

    await page.goto('/admin/schedule');
    await expect(page.getByTestId('schedule-page')).toBeVisible();

    // Fill in credentials
    await page.getByTestId('schedule-username-input').fill(admin.username);
    await page.getByTestId('schedule-password-input').fill(admin.password);
    await page.getByTestId('schedule-save-btn').click();

    // Wait for profile to load - the page should show schedule content
    // View tabs should remain visible after auth
    await expect(page.getByRole('tab', { name: 'Day' })).toBeVisible();
  });
});
