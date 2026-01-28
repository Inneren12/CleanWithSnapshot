import { expect, test } from '@playwright/test';

import {
  defaultAdminCredentials,
  seedAdminStorage,
  verifyAdminCredentials,
} from './helpers/adminAuth';

test.describe('Inventory page', () => {
  test.beforeEach(async ({ page, request }) => {
    const admin = defaultAdminCredentials();
    await verifyAdminCredentials(request, admin);
    await seedAdminStorage(page, admin);
  });

  test('inventory page loads with all sections', async ({ page }) => {
    await page.goto('/admin/inventory');

    await expect(page.getByTestId('inventory-page')).toBeVisible();
    await expect(page.getByTestId('inventory-header-section')).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Inventory items' })).toBeVisible();
  });

  test('inventory page shows low stock section', async ({ page }) => {
    await page.goto('/admin/inventory');

    await expect(page.getByTestId('inventory-page')).toBeVisible();

    // Low stock section should be visible
    await expect(page.getByTestId('inventory-low-stock-section')).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Low stock' })).toBeVisible();
    await expect(page.getByTestId('low-stock-count')).toBeVisible();
  });

  test('inventory page shows inventory list section', async ({ page }) => {
    await page.goto('/admin/inventory');

    await expect(page.getByTestId('inventory-page')).toBeVisible();

    // Inventory list section should be visible
    await expect(page.getByTestId('inventory-list-section')).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Inventory list' })).toBeVisible();
  });

  test('inventory credentials can be saved', async ({ page }) => {
    const admin = defaultAdminCredentials();

    await page.goto('/admin/inventory');
    await expect(page.getByTestId('inventory-page')).toBeVisible();

    // Fill in credentials
    await page.getByTestId('inventory-username-input').fill(admin.username);
    await page.getByTestId('inventory-password-input').fill(admin.password);
    await page.getByTestId('inventory-save-btn').click();

    // Should see status message
    await expect(page.getByTestId('inventory-status-message')).toBeVisible();
    await expect(page.getByTestId('inventory-status-message')).toContainText('Saved');
  });

  test('inventory search input is functional', async ({ page }) => {
    const admin = defaultAdminCredentials();

    await page.goto('/admin/inventory');
    await expect(page.getByTestId('inventory-page')).toBeVisible();

    // Set credentials first
    await page.getByTestId('inventory-username-input').fill(admin.username);
    await page.getByTestId('inventory-password-input').fill(admin.password);
    await page.getByTestId('inventory-save-btn').click();

    // Search input should be functional
    const searchInput = page.getByTestId('inventory-search-input');
    await expect(searchInput).toBeVisible();
    await searchInput.fill('test search');
    await expect(searchInput).toHaveValue('test search');
  });

  test('inventory table is displayed', async ({ page }) => {
    const admin = defaultAdminCredentials();

    await page.goto('/admin/inventory');
    await expect(page.getByTestId('inventory-page')).toBeVisible();

    // Set credentials first
    await page.getByTestId('inventory-username-input').fill(admin.username);
    await page.getByTestId('inventory-password-input').fill(admin.password);
    await page.getByTestId('inventory-save-btn').click();

    // Wait for table to appear
    await expect(page.getByTestId('inventory-table')).toBeVisible();
  });
});
