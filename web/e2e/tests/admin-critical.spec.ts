import { expect, test } from '@playwright/test';

import {
  defaultAdminCredentials,
  seedAdminStorage,
  verifyAdminCredentials,
} from './helpers/adminAuth';

test.describe('Admin critical flow', () => {
  test('login and open leads dashboard', async ({ page, request }) => {
    const admin = defaultAdminCredentials();

    await verifyAdminCredentials(request, admin);
    await seedAdminStorage(page, admin);

    await page.goto('/admin');

    await expect(
      page.getByRole('heading', { name: 'Admin / Dispatcher' })
    ).toBeVisible();
    await expect(page.getByTestId('admin-shell-ready')).toBeVisible();

    await page.goto('/admin/leads');
    await expect(page.getByRole('heading', { name: 'Leads' })).toBeVisible();
    await expect(
      page.getByRole('heading', { name: 'Pipeline' })
    ).toBeVisible();
  });
});
