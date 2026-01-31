import { expect, test } from '@playwright/test';
import type { APIResponse } from '@playwright/test';

import {
  adminAuthHeaders,
  defaultAdminCredentials,
  seedAdminStorage,
  verifyAdminCredentials,
} from './helpers/adminAuth';

const formatDate = (value: Date) => value.toISOString().slice(0, 10);

async function buildResponseDebugMessage(
  response: APIResponse,
  url: string
): Promise<string> {
  try {
    const body = await response.text();
    return `Request failed: ${response.status()} ${response.statusText()} url=${url} body=${body}`;
  } catch (error) {
    return `Request failed: ${response.status()} ${response.statusText()} url=${url} body=<unreadable:${String(
      error
    )}>`;
  }
}

test.describe('Invoice payment flow', () => {
  test.beforeEach(async ({ page, request }) => {
    const admin = defaultAdminCredentials();
    await verifyAdminCredentials(request, admin);
    await seedAdminStorage(page, admin);
  });

  test('invoice payment flow records a manual payment', async ({ page }, testInfo) => {
    const admin = defaultAdminCredentials();
    const authHeaders = adminAuthHeaders(admin);
    const runSuffix = `${testInfo.workerIndex}-${testInfo.retry}`;

    const bookingStart = new Date();
    bookingStart.setUTCDate(bookingStart.getUTCDate() + 1);
    bookingStart.setUTCHours(18, 0, 0, 0);

    const bookingPayload = {
      starts_at: bookingStart.toISOString(),
      duration_minutes: 120,
      client: {
        name: 'E2E Invoice Client',
        email: `e2e-invoice-${runSuffix}-${Date.now()}@example.com`,
        phone: '555-0101',
      },
      address_text: '123 Test Street',
      price_cents: 15000,
      addon_ids: [],
    };

    const bookingUrl = `${admin.apiBaseUrl}/v1/admin/schedule/quick-create`;
    const bookingResponse = await page.request.post(bookingUrl, {
      data: bookingPayload,
      headers: {
        ...authHeaders,
        'Content-Type': 'application/json',
      },
    });

    const bookingDebugMessage = bookingResponse.ok()
      ? 'Booking request succeeded'
      : await buildResponseDebugMessage(bookingResponse, bookingUrl);
    expect(bookingResponse.ok(), bookingDebugMessage).toBeTruthy();
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

    const invoiceUrl = `${admin.apiBaseUrl}/v1/admin/orders/${booking.booking_id}/invoice`;
    const invoiceResponse = await page.request.post(invoiceUrl, {
      data: invoicePayload,
      headers: {
        ...authHeaders,
        'Content-Type': 'application/json',
        'X-CSRF-Token': csrfToken,
      },
    });

    const invoiceDebugMessage = invoiceResponse.ok()
      ? 'Invoice creation succeeded'
      : await buildResponseDebugMessage(invoiceResponse, invoiceUrl);
    expect(invoiceResponse.ok(), invoiceDebugMessage).toBeTruthy();
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

    const paymentForm = page.locator('form', { hasText: 'Record Manual Payment' });

    await expect(paymentForm).toBeVisible();

    const amountField = paymentForm.getByLabel(/Amount/i);
    const methodField = paymentForm.getByLabel('Payment Method');
    const referenceField = paymentForm.getByLabel(/Reference/i);

    await expect(amountField).toBeVisible();
    await expect(amountField).toBeEnabled();
    await expect(methodField).toBeVisible();
    await expect(methodField).toBeEnabled();
    await expect(referenceField).toBeVisible();

    const paymentAmount = (invoice.total_cents / 100).toFixed(2);
    await amountField.fill(paymentAmount);
    await methodField.selectOption('card');
    await referenceField.fill('e2e-payment');
    await paymentForm.getByRole('button', { name: 'Record Payment' }).click();

    await expect(page.getByText('Payment recorded successfully!')).toBeVisible();
    await expect(page.getByText('PAID', { exact: true })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Payments' })).toBeVisible();
    await expect(page.getByText('via card')).toBeVisible();
  });
});
