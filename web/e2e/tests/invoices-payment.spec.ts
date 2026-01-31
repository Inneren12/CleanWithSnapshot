import { expect, test } from '@playwright/test';
import type { APIRequestContext, APIResponse } from '@playwright/test';

import {
  adminAuthHeaders,
  defaultAdminCredentials,
  seedAdminStorage,
  verifyAdminCredentials,
} from './helpers/adminAuth';

const formatDate = (value: Date) => value.toISOString().slice(0, 10);

const trimPayload = (value: string, limit = 400) =>
  value.length > limit ? `${value.slice(0, limit)}…` : value;

const getHeaderValue = (response: APIResponse, key: string) =>
  response.headers()[key.toLowerCase()] ?? '';

type DebugDetails = {
  message: string;
  requestId?: string;
};

async function buildResponseDebugDetails(
  response: APIResponse,
  url: string
): Promise<DebugDetails> {
  const statusLine = `${response.status()} ${response.statusText()}`.trim();
  const contentType = getHeaderValue(response, 'content-type');
  const headerRequestId = getHeaderValue(response, 'x-request-id');
  const isJson = contentType.includes('application/json') || contentType.includes('+json');
  try {
    const lines: string[] = [];
    let requestId = headerRequestId || undefined;
    if (isJson) {
      const payload = await response.json();
      requestId = payload?.request_id ?? requestId;
      const title = payload?.title ? `title=${payload.title}` : '';
      const detail = payload?.detail ? `detail=${payload.detail}` : '';
      const detailsLine =
        title || detail ? `problem_details: ${[title, detail].filter(Boolean).join(' ')}` : '';
      const payloadString = JSON.stringify(payload);
      const trimmedPayload = trimPayload(payloadString);
      lines.push(
        `Request failed: ${statusLine} url=${url}${requestId ? ` request_id=${requestId}` : ''}`
      );
      if (detailsLine) {
        lines.push(detailsLine);
      }
      lines.push(
        `headers: content-type=${contentType || 'unknown'} x-request-id=${
          headerRequestId || 'unknown'
        }`
      );
      lines.push(`body=${trimmedPayload}`);
      return { message: lines.join('\n'), requestId };
    }
    const body = await response.text();
    const trimmed = trimPayload(body);
    lines.push(
      `Request failed: ${statusLine} url=${url}${requestId ? ` request_id=${requestId}` : ''}`
    );
    lines.push(
      `headers: content-type=${contentType || 'unknown'} x-request-id=${
        headerRequestId || 'unknown'
      }`
    );
    lines.push(`body=${trimmed}`);
    return { message: lines.join('\n'), requestId };
  } catch (error) {
    return {
      message: `Request failed: ${statusLine} url=${url} body=<unreadable:${String(error)}>`,
    };
  }
}

async function fetchHealthSnapshot(
  request: APIRequestContext,
  apiBaseUrl: string,
  headers: Record<string, string>
): Promise<string> {
  const endpoints = ['healthz', 'readyz'];
  const results: string[] = [];
  for (const endpoint of endpoints) {
    const url = `${apiBaseUrl}/${endpoint}`;
    try {
      const response = await request.get(url, { headers });
      const body = trimPayload(await response.text(), 200);
      results.push(`${endpoint}: ${response.status()} ${response.statusText()} body=${body}`);
    } catch (error) {
      results.push(`${endpoint}: failed (${String(error)})`);
    }
  }
  return `health snapshot: ${results.join(' | ')}`;
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

    let bookingDebugMessage = 'Booking request succeeded';
    if (!bookingResponse.ok()) {
      const debugDetails = await buildResponseDebugDetails(bookingResponse, bookingUrl);
      const healthSnapshot = await fetchHealthSnapshot(
        page.request,
        admin.apiBaseUrl,
        authHeaders
      );
      const hint = debugDetails.requestId
        ? `Search in API logs for request_id=${debugDetails.requestId} or key=schedule_quick_create_failed`
        : 'Search in API logs for key=schedule_quick_create_failed';
      bookingDebugMessage = [debugDetails.message, hint, healthSnapshot].join('\n');
    }
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
      : (await buildResponseDebugDetails(invoiceResponse, invoiceUrl)).message;
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

    const amountField = paymentForm.getByLabel(`Amount (${invoice.currency})`, { exact: true });
    const methodField = paymentForm.getByLabel('Payment Method', { exact: true });
    const referenceField = paymentForm.getByLabel('Reference (optional)', { exact: true });

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
