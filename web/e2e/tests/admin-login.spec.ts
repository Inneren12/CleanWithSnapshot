import { expect, test } from '@playwright/test';

import {
  defaultAdminCredentials,
  seedAdminStorage,
  verifyAdminCredentials,
} from './helpers/adminAuth';

test.describe('Admin login flow', () => {
  test('login via credential form saves to localStorage', async ({ page, request }) => {
    const admin = defaultAdminCredentials();

    // First verify credentials are valid via API
    await verifyAdminCredentials(request, admin);

    // Navigate to admin dashboard without pre-seeded storage
    await page.goto('/admin');

    // Should see credential inputs
    await expect(page.getByTestId('admin-login-form')).toBeVisible();
    const usernameInput = page.getByTestId('admin-username-input');
    const passwordInput = page.getByTestId('admin-password-input');
    const saveButton = page.getByTestId('admin-save-credentials-btn');

    await expect(usernameInput).toBeVisible();
    await expect(passwordInput).toBeVisible();
    await expect(saveButton).toBeVisible();

    // Fill in credentials
    await usernameInput.fill(admin.username);
    await passwordInput.fill(admin.password);
    await saveButton.click();

    // Should see success message
    await expect(page.getByTestId('admin-message')).toBeVisible();

    // Verify admin shell is ready
    await expect(page.getByTestId('admin-shell-ready')).toBeVisible();
  });

  test('login persists after page reload', async ({ page, request }) => {
    const admin = defaultAdminCredentials();

    await verifyAdminCredentials(request, admin);
    await seedAdminStorage(page, admin);

    await page.goto('/admin');
    await expect(page.getByTestId('admin-shell-ready')).toBeVisible();

    // Reload the page
    await page.reload();

    // Should still be logged in
    await expect(page.getByTestId('admin-shell-ready')).toBeVisible();
    await expect(
      page.getByRole('heading', { name: 'Admin / Dispatcher' })
    ).toBeVisible();
  });

  test('clear credentials logs out user', async ({ page, request }) => {
    const admin = defaultAdminCredentials();

    await verifyAdminCredentials(request, admin);
    await seedAdminStorage(page, admin);

    await page.goto('/admin');
    await expect(page.getByTestId('admin-shell-ready')).toBeVisible();

    // Click clear credentials
    const clearButton = page.getByTestId('admin-clear-credentials-btn');
    await clearButton.waitFor({ state: 'visible' });
    await expect(clearButton).toBeEnabled();
    await clearButton.click();

    // Should see cleared message
    await expect(page.getByTestId('admin-message')).toContainText('Cleared');

    await expect
      .poll(
        () =>
          page.evaluate(() => ({
            username: window.localStorage.getItem('admin_basic_username'),
            password: window.localStorage.getItem('admin_basic_password'),
          })),
        { timeout: 30_000 }
      )
      .toEqual({ username: null, password: null });

    // After reload, should need to log in again
    await page.reload();
    await expect(page.getByTestId('admin-login-form')).toBeVisible({
      timeout: 30_000,
    });
    await expect(page.getByTestId('admin-username-input')).toBeVisible({
      timeout: 30_000,
    });
  });
});
