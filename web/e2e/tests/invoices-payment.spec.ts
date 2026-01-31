import { expect, test } from '@playwright/test';

import {
  adminAuthHeaders,
  defaultAdminCredentials,
  seedAdminStorage,
  verifyAdminCredentials,
} from './helpers/adminAuth';

const formatDate = (value: Date) => value.toISOString().slice(0, 10);

test.describe('Invoice payment flow', () => {
  test.beforeEach(async ({ page, request }) => {
    const admin = defaultAdminCredentials();
    await verifyAdminCredentials(request, admin);
    await seedAdminStorage(page, admin);
  });

  test('invoice payment flow records a manual payment', async ({ page }) => {
    const admin = defaultAdminCredentials();
    const authHeaders = adminAuthHeaders(admin);

    const bookingPayload = {
      starts_at: new Date(Date.now() + 24 * 60 * 60 * 1000).toISOString(),
      duration_minutes: 120,
      client: {
        name: 'E2E Invoice Client',
        email: `e2e-invoice-${Date.now()}@example.com`,
        phone: '555-0101',
      },
      address_text: '123 Test Street',
      price_cents: 15000,
      addon_ids: [],
    };

    const bookingResponse = await page.request.post(
      `${admin.apiBaseUrl}/v1/admin/schedule/quick-create`,
      {
        data: bookingPayload,
        headers: {
          ...authHeaders,
          'Content-Type': 'application/json',
        },
      }
    );

    expect(bookingResponse.ok()).toBeTruthy();
    const booking = await bookingResponse.json();
    expect(booking.booking_id).toBeTruthy();

    const csrfToken = `e2e-${Date.now()}`;
    await page.context().addCookies([
      {
        name: 'csrf_token',
        value: csrfToken,
        url: admin.apiBaseUrl,
      },
    ]);

    const invoicePayload = {
      issue_date: formatDate(new Date()),
      due_date: formatDate(new Date(Date.now() + 7 * 24 * 60 * 60 * 1000)),
      currency: 'CAD',
      items: [
        {
          description: 'E2E cleaning service',
          qty: 1,
          unit_price_cents: 15000,
          tax_rate: 0,
        },
      ],
    };

    const invoiceResponse = await page.request.post(
      `${admin.apiBaseUrl}/v1/admin/orders/${booking.booking_id}/invoice`,
      {
        data: invoicePayload,
        headers: {
          ...authHeaders,
          'Content-Type': 'application/json',
          'X-CSRF-Token': csrfToken,
        },
      }
    );

    expect(invoiceResponse.ok()).toBeTruthy();
    const invoice = await invoiceResponse.json();
    expect(invoice.invoice_id).toBeTruthy();

    await page.goto(`/admin/invoices/${invoice.invoice_id}`);

    await expect(
      page.getByRole('heading', { name: invoice.invoice_number })
    ).toBeVisible();

    await page.getByRole('button', { name: 'Record Manual Payment' }).click();
    await expect(
      page.getByRole('heading', { name: 'Record Manual Payment' })
    ).toBeVisible();

    const paymentAmount = (invoice.total_cents / 100).toFixed(2);
    const paymentForm = page.locator('form', { hasText: 'Record Manual Payment' });

    await paymentForm.getByLabel(/Amount/).fill(paymentAmount);
    await paymentForm.getByLabel('Payment Method').selectOption('card');
    await paymentForm.getByLabel(/Reference/).fill('e2e-payment');
    await paymentForm.getByRole('button', { name: 'Record Payment' }).click();

    await expect(page.getByText('Payment recorded successfully!')).toBeVisible();
    await expect(page.getByText('PAID', { exact: true })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Payments' })).toBeVisible();
    await expect(page.getByText('via card')).toBeVisible();
  });
});
