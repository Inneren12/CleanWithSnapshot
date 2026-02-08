import { expect, test, type Page } from '@playwright/test';

import {
  defaultAdminCredentials,
  seedAdminStorage,
  verifyAdminCredentials,
} from './helpers/adminAuth';
import { waitForAdminPage } from './helpers/playwrightContext';

const waitForLeadsReady = async (page: Page) => {
  const refreshButton = page.getByTestId('leads-refresh');
  await expect(refreshButton).toBeVisible({ timeout: 30_000 });
  await expect(refreshButton).not.toHaveText(/Loading/i, { timeout: 30_000 });
  await expect(refreshButton).toBeEnabled({ timeout: 30_000 });
};

test.describe('Leads management', () => {
  test.beforeEach(async ({ page, request }) => {
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

  test('leads section loads on admin dashboard', async ({ page }) => {
    await page.goto('/admin');

    await expect(page.getByTestId('admin-shell-ready')).toBeVisible();
    await expect(page.getByTestId('admin-leads-section')).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Leads' })).toBeVisible();
  });

  test('leads table is displayed', async ({ page }) => {
    await page.goto('/admin');

    await expect(page.getByTestId('admin-shell-ready')).toBeVisible();
    await expect(page.getByTestId('leads-table')).toBeVisible();
  });

  test('leads status filter is functional', async ({ page }) => {
    await page.goto('/admin');

    await expect(page.getByTestId('admin-shell-ready')).toBeVisible();
    // Ensure no error page takeover
    await expect(page.locator('html#__next_error__')).toHaveCount(0);

    // Wait for stable controls wrapper
    await expect(page.getByTestId('leads-controls')).toBeVisible();
    await waitForLeadsReady(page);
    await expect(page.getByTestId('leads-table')).toBeVisible({ timeout: 30_000 });

    const statusFilter = page.getByTestId('leads-status-filter');
    await expect(statusFilter).toBeVisible({ timeout: 30_000 });
    await expect(statusFilter).toBeEnabled({ timeout: 30_000 });
    const applyButton = page.getByTestId('leads-status-apply');
    await expect(applyButton).toBeVisible({ timeout: 30_000 });
    await expect(applyButton).toBeEnabled({ timeout: 30_000 });

    // Type a filter value
    const waitForLeads = page.waitForResponse((response) => {
      return (
        response.request().method() === 'GET' &&
        response.url().includes('/v1/admin/leads') &&
        response.url().includes('status=NEW') &&
        response.ok()
      );
    });
    await statusFilter.fill('New');
    await applyButton.click();
    await waitForLeads;
    await expect(statusFilter).toHaveValue('NEW');
    await expect(page.getByTestId('leads-table')).toBeVisible({ timeout: 30_000 });
  });

  test('leads refresh button is functional', async ({ page }) => {
    await page.goto('/admin');

    await expect(page.getByTestId('admin-shell-ready')).toBeVisible();
    // Ensure no error page takeover
    await expect(page.locator('html#__next_error__')).toHaveCount(0);

    // Wait for stable controls wrapper
    await expect(page.getByTestId('leads-controls')).toBeVisible();
    await waitForLeadsReady(page);

    const refreshButton = page.getByTestId('leads-refresh');
    await expect(refreshButton).toBeVisible({ timeout: 30_000 });
    await expect(refreshButton).toBeEnabled({ timeout: 30_000 });
    await expect(page.getByTestId('leads-table')).toBeVisible({ timeout: 30_000 });

    // Click refresh button
    const waitForLeads = page.waitForResponse((response) => {
      return (
        response.request().method() === 'GET' &&
        response.url().includes('/v1/admin/leads') &&
        response.ok()
      );
    });
    await refreshButton.click();
    await waitForLeads;

    // Ensure no error page takeover after click
    await expect(page.locator('html#__next_error__')).toHaveCount(0);

    // Table should still be visible after refresh
    await expect(page.getByTestId('leads-table')).toBeVisible();
  });

  test('dedicated leads page loads', async ({ page }) => {
    await waitForAdminPage({ page, path: '/admin/leads', rootTestId: 'leads-page' });

    await expect(page.getByTestId('leads-page')).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Leads' })).toBeVisible();
    await expect(page.getByTestId('leads-pipeline-section')).toBeVisible();
  });

  test('leads page shows pipeline stages', async ({ page }) => {
    await waitForAdminPage({ page, path: '/admin/leads', rootTestId: 'leads-page' });

    await expect(page.getByTestId('leads-page')).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Pipeline' })).toBeVisible();

    // Check for pipeline stage controls
    await expect(page.getByTestId('leads-pipeline')).toBeVisible();
    await expect(page.getByTestId('pipeline-stage-new')).toBeVisible();
    await expect(page.getByTestId('pipeline-stage-contacted')).toBeVisible();
    await expect(page.getByTestId('pipeline-stage-quoted')).toBeVisible();
    await expect(page.getByTestId('pipeline-stage-won')).toBeVisible();
    await expect(page.getByTestId('pipeline-stage-lost')).toBeVisible();

    await expect(page.getByTestId('leads-list')).toBeVisible();
  });
});
