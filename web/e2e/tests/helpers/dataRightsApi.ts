import crypto from 'crypto';
import type { APIRequestContext } from '@playwright/test';

import { AdminCredentials, defaultAdminCredentials } from './adminAuth';

const ADMIN_PROXY_AUTH_ENABLED =
  (process.env.ADMIN_PROXY_AUTH_ENABLED ?? '').toLowerCase() === 'true';
const ADMIN_PROXY_AUTH_SECRET = process.env.ADMIN_PROXY_AUTH_SECRET ?? '';
const ADMIN_PROXY_AUTH_ROLE = process.env.ADMIN_PROXY_AUTH_ROLE ?? 'admin';
const ADMIN_PROXY_AUTH_E2E_ENABLED =
  (process.env.ADMIN_PROXY_AUTH_E2E_ENABLED ?? '').toLowerCase() === 'true';
const ADMIN_PROXY_AUTH_E2E_SECRET = process.env.ADMIN_PROXY_AUTH_E2E_SECRET ?? '';
const ADMIN_PROXY_AUTH_E2E_USER = process.env.ADMIN_PROXY_AUTH_E2E_USER ?? '';
const ADMIN_PROXY_AUTH_E2E_EMAIL = process.env.ADMIN_PROXY_AUTH_E2E_EMAIL ?? '';
const ADMIN_PROXY_AUTH_E2E_ROLES = process.env.ADMIN_PROXY_AUTH_E2E_ROLES ?? '';
const SAAS_E2E_EMAIL = process.env.SAAS_E2E_EMAIL;

const buildE2eEmail = (prefix: string): string =>
  `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}@example.com`;

export type DataExportResponse = {
  leads: Array<Record<string, unknown>>;
  bookings: Array<Record<string, unknown>>;
  invoices: Array<Record<string, unknown>>;
  payments: Array<Record<string, unknown>>;
  photos: Array<Record<string, unknown>>;
};

export type DataRightsExportRequestResponse = {
  export_id: string;
  status: string;
  created_at: string;
};

export type DataRightsExportListItem = {
  export_id: string;
  status: string;
  created_at: string;
  completed_at: string | null;
};

export type DataRightsExportListResponse = {
  items: DataRightsExportListItem[];
  total: number;
};

export type DataDeletionResponse = {
  request_id: string;
  status: string;
  matched_leads: number;
  pending_deletions: number;
  requested_at: string;
};

type AdminUserCreateResponse = {
  user_id: string;
  email: string;
  target_type: string;
  must_change_password: boolean;
  temp_password: string;
};

type LoginResponse = {
  access_token: string;
  refresh_token?: string | null;
  org_id: string;
  role: string;
  expires_at?: string | null;
  must_change_password: boolean;
  mfa_verified: boolean;
};

const buildProxyHeaders = (credentials: AdminCredentials): Record<string, string> => {
  const mfaValue = 'true';
  const headers: Record<string, string> = {
    'X-Proxy-Auth-Secret': ADMIN_PROXY_AUTH_SECRET,
    'X-Auth-MFA': mfaValue,
  };

  if (ADMIN_PROXY_AUTH_E2E_ENABLED && ADMIN_PROXY_AUTH_E2E_SECRET) {
    const user = ADMIN_PROXY_AUTH_E2E_USER || credentials.username;
    const email =
      ADMIN_PROXY_AUTH_E2E_EMAIL || `${credentials.username}@example.com`;
    const roles = ADMIN_PROXY_AUTH_E2E_ROLES || ADMIN_PROXY_AUTH_ROLE;
    const timestamp = Math.floor(Date.now() / 1000).toString();
    const payload = [user, email, roles, timestamp, mfaValue].join('\n');
    const signature = crypto
      .createHmac('sha256', ADMIN_PROXY_AUTH_E2E_SECRET)
      .update(payload)
      .digest('hex');
    headers['X-E2E-Admin-User'] = user;
    headers['X-E2E-Admin-Email'] = email;
    headers['X-E2E-Admin-Roles'] = roles;
    headers['X-E2E-Proxy-Timestamp'] = timestamp;
    headers['X-E2E-Proxy-Signature'] = signature;
    return headers;
  }

  headers['X-Admin-User'] = credentials.username;
  headers['X-Admin-Roles'] = ADMIN_PROXY_AUTH_ROLE;
  return headers;
};

function getAdminAuthHeaders(credentials: AdminCredentials): Record<string, string> {
  if (ADMIN_PROXY_AUTH_ENABLED) {
    return buildProxyHeaders(credentials);
  }
  return {
    Authorization: `Basic ${Buffer.from(`${credentials.username}:${credentials.password}`).toString('base64')}`,
  };
}

let cachedSaasAuthHeaders: Record<string, string> | null = null;
let cachedSaasAuthHeadersPromise: Promise<Record<string, string>> | null = null;

async function getSaasAuthHeaders(
  request: APIRequestContext
): Promise<Record<string, string>> {
  if (cachedSaasAuthHeaders) {
    return cachedSaasAuthHeaders;
  }
  if (cachedSaasAuthHeadersPromise) {
    return cachedSaasAuthHeadersPromise;
  }

  cachedSaasAuthHeadersPromise = (async () => {
    const credentials = defaultAdminCredentials();
    const createUser = async (email: string): Promise<AdminUserCreateResponse> => {
      const response = await request.post(`${credentials.apiBaseUrl}/v1/admin/users`, {
        headers: {
          ...getAdminAuthHeaders(credentials),
          'Content-Type': 'application/json',
        },
        data: {
          email,
          target_type: 'client',
          name: 'E2E Data Rights',
          role: 'admin',
        },
      });

      if (response.status() === 409) {
        throw new Error('USER_EXISTS');
      }
      if (!response.ok()) {
        const text = await response.text();
        throw new Error(`Failed to create SaaS user (${response.status()}): ${text}`);
      }

      return (await response.json()) as AdminUserCreateResponse;
    };

    let createdUser: AdminUserCreateResponse;
    try {
      const preferredEmail =
        SAAS_E2E_EMAIL ?? buildE2eEmail('e2e-data-rights');
      createdUser = await createUser(preferredEmail);
    } catch (error) {
      if (error instanceof Error && error.message === 'USER_EXISTS') {
        createdUser = await createUser(buildE2eEmail('e2e-data-rights'));
      } else {
        throw error;
      }
    }
    const loginResponse = await request.post(`${credentials.apiBaseUrl}/v1/auth/login`, {
      headers: {
        'Content-Type': 'application/json',
      },
      data: {
        email: createdUser.email,
        password: createdUser.temp_password,
      },
    });

    if (!loginResponse.ok()) {
      const text = await loginResponse.text();
      throw new Error(`SaaS login failed (${loginResponse.status()}): ${text}`);
    }

    const loginPayload = (await loginResponse.json()) as LoginResponse;

    if (!loginPayload?.access_token) {
      throw new Error(
        `Login succeeded but no access_token in response. ` +
        `Status: ${loginResponse.status()}, Body: ${JSON.stringify(loginPayload)}`
      );
    }

    let accessToken = loginPayload.access_token;

    if (loginPayload.must_change_password) {
      const newPassword = `E2eDataRights${crypto.randomUUID()}1A`;
      const changeResponse = await request.post(
        `${credentials.apiBaseUrl}/v1/auth/change-password`,
        {
          headers: {
            Authorization: `Bearer ${accessToken}`,
            'Content-Type': 'application/json',
          },
          data: {
            current_password: createdUser.temp_password,
            new_password: newPassword,
          },
        }
      );

      if (!changeResponse.ok()) {
        const text = await changeResponse.text();
        throw new Error(`Change password failed (${changeResponse.status()}): ${text}`);
      }

      const changePayload = (await changeResponse.json()) as LoginResponse;

      if (!changePayload?.access_token) {
        throw new Error(
          `Password change succeeded but no access_token in response. ` +
          `Status: ${changeResponse.status()}, Body: ${JSON.stringify(changePayload)}`
        );
      }

      accessToken = changePayload.access_token;

      if (typeof accessToken !== 'string' || accessToken.split('.').length !== 3) {
        throw new Error(
          `Invalid JWT format after password change. ` +
          `Token: ${accessToken}, Expected 3 parts (header.payload.signature)`
        );
      }
    }

    console.log('[getSaasAuthHeaders] Successfully obtained SaaS JWT:', {
      tokenPreview: accessToken.substring(0, 50) + '...',
      tokenParts: accessToken.split('.').length,
    });

    cachedSaasAuthHeaders = {
      Authorization: `Bearer ${accessToken}`,
    };
    return cachedSaasAuthHeaders;
  })();

  try {
    cachedSaasAuthHeaders = await cachedSaasAuthHeadersPromise;
    return cachedSaasAuthHeaders;
  } finally {
    cachedSaasAuthHeadersPromise = null;
  }
}

/**
 * Request a data export for a lead (synchronous admin export).
 * Returns the export bundle immediately.
 */
export async function requestDataExportSync(
  request: APIRequestContext,
  options: { leadId?: string; email?: string }
): Promise<{ response: DataExportResponse; status: number }> {
  const credentials = defaultAdminCredentials();
  const response = await request.post(`${credentials.apiBaseUrl}/v1/admin/data/export`, {
    headers: {
      ...getAdminAuthHeaders(credentials),
      'Content-Type': 'application/json',
    },
    data: {
      lead_id: options.leadId,
      email: options.email,
    },
  });

  const status = response.status();
  if (!response.ok()) {
    const text = await response.text();
    console.error(`Data export failed (${status}): ${text}`);
    throw new Error(`Data export failed: ${status} - ${text}`);
  }

  return { response: await response.json(), status };
}

/**
 * Request a data export (async flow via data-rights endpoint).
 * Returns export request metadata (export_id, status).
 */
export async function requestDataExportAsync(
  request: APIRequestContext,
  options?: { leadId?: string; email?: string }
): Promise<{ response: DataRightsExportRequestResponse; status: number }> {
  const credentials = defaultAdminCredentials();
  const saasHeaders = await getSaasAuthHeaders(request);
  const response = await request.post(
    `${credentials.apiBaseUrl}/v1/data-rights/export-request`,
    {
      headers: {
        ...saasHeaders,
        'Content-Type': 'application/json',
      },
      data: options ? { lead_id: options.leadId, email: options.email } : {},
    }
  );

  const status = response.status();
  if (!response.ok()) {
    const text = await response.text();
    console.error(`Async export request failed (${status}): ${text}`);
    throw new Error(`Async export request failed: ${status} - ${text}`);
  }

  return { response: await response.json(), status };
}

/**
 * List data export requests for a subject.
 */
export async function listDataExports(
  request: APIRequestContext,
  options?: { leadId?: string; email?: string }
): Promise<{ response: DataRightsExportListResponse; status: number }> {
  const credentials = defaultAdminCredentials();
  const saasHeaders = await getSaasAuthHeaders(request);
  const params = new URLSearchParams();
  if (options?.leadId) params.set('lead_id', options.leadId);
  if (options?.email) params.set('email', options.email);

  const url = `${credentials.apiBaseUrl}/v1/data-rights/exports${params.toString() ? `?${params}` : ''}`;
  const response = await request.get(url, {
    headers: saasHeaders,
  });

  const status = response.status();
  if (!response.ok()) {
    const text = await response.text();
    console.error(`List exports failed (${status}): ${text}`);
    throw new Error(`List exports failed: ${status} - ${text}`);
  }

  return { response: await response.json(), status };
}

/**
 * Download a completed data export.
 * Returns the download response or redirect URL.
 */
export async function downloadDataExport(
  request: APIRequestContext,
  exportId: string
): Promise<{ body: Buffer | null; status: number; contentType: string | null }> {
  const credentials = defaultAdminCredentials();
  const saasHeaders = await getSaasAuthHeaders(request);
  const response = await request.get(
    `${credentials.apiBaseUrl}/v1/data-rights/exports/${exportId}/download`,
    {
      headers: saasHeaders,
      maxRedirects: 0,
    }
  );

  const status = response.status();
  const contentType = response.headers()['content-type'] ?? null;

  if (status === 307) {
    // Redirect to signed URL - this is expected for cloud storage
    return { body: null, status, contentType };
  }

  if (!response.ok() && status !== 307) {
    const text = await response.text();
    console.error(`Download export failed (${status}): ${text}`);
    throw new Error(`Download export failed: ${status} - ${text}`);
  }

  const body = await response.body();
  return { body, status, contentType };
}

/**
 * Request data deletion for a lead.
 */
export async function requestDataDeletion(
  request: APIRequestContext,
  options: { leadId?: string; email?: string; reason?: string }
): Promise<{ response: DataDeletionResponse; status: number }> {
  const credentials = defaultAdminCredentials();
  const response = await request.post(
    `${credentials.apiBaseUrl}/v1/admin/data-deletion/requests`,
    {
      headers: {
        ...getAdminAuthHeaders(credentials),
        'Content-Type': 'application/json',
      },
      data: {
        lead_id: options.leadId,
        email: options.email,
        reason: options.reason,
      },
    }
  );

  const status = response.status();
  if (!response.ok()) {
    const text = await response.text();
    console.error(`Deletion request failed (${status}): ${text}`);
    throw new Error(`Deletion request failed: ${status} - ${text}`);
  }

  return { response: await response.json(), status };
}

/**
 * Run retention cleanup (processes pending deletions).
 */
export async function runRetentionCleanup(
  request: APIRequestContext
): Promise<{ response: Record<string, number>; status: number }> {
  const credentials = defaultAdminCredentials();
  const response = await request.post(
    `${credentials.apiBaseUrl}/v1/admin/retention/cleanup`,
    {
      headers: getAdminAuthHeaders(credentials),
    }
  );

  const status = response.status();
  if (!response.ok()) {
    const text = await response.text();
    console.error(`Retention cleanup failed (${status}): ${text}`);
    throw new Error(`Retention cleanup failed: ${status} - ${text}`);
  }

  return { response: await response.json(), status };
}

/**
 * Trigger processing of pending data exports (test-only endpoint).
 * This should only be available when E2E_TEST_MODE=1.
 */
export async function processDataExports(
  request: APIRequestContext
): Promise<{ response: Record<string, number>; status: number }> {
  const credentials = defaultAdminCredentials();
  const response = await request.post(
    `${credentials.apiBaseUrl}/v1/admin/test/process-data-exports`,
    {
      headers: getAdminAuthHeaders(credentials),
    }
  );

  const status = response.status();
  if (!response.ok()) {
    const text = await response.text();
    // Don't throw if endpoint doesn't exist (404) - test hook may not be enabled
    if (status === 404) {
      console.warn('Test endpoint /v1/admin/test/process-data-exports not available');
      return { response: { processed: 0, completed: 0, failed: 0 }, status };
    }
    console.error(`Process exports failed (${status}): ${text}`);
    throw new Error(`Process exports failed: ${status} - ${text}`);
  }

  return { response: await response.json(), status };
}

/**
 * Poll for export completion with deterministic retries.
 * Returns the export when completed or throws if max retries exceeded.
 */
export async function waitForExportCompletion(
  request: APIRequestContext,
  exportId: string,
  options?: {
    maxRetries?: number;
    pollIntervalMs?: number;
    leadId?: string;
    email?: string;
  }
): Promise<DataRightsExportListItem> {
  const maxRetries = options?.maxRetries ?? 30;
  const pollIntervalMs = options?.pollIntervalMs ?? 1000;

  for (let attempt = 0; attempt < maxRetries; attempt++) {
    // Try to trigger job processing (if test hook is available)
    if (attempt > 0 && attempt % 3 === 0) {
      try {
        await processDataExports(request);
      } catch {
        // Ignore - test hook may not be available
      }
    }

    const { response } = await listDataExports(request, {
      leadId: options?.leadId,
      email: options?.email,
    });

    const exportItem = response.items.find((item) => item.export_id === exportId);
    if (exportItem) {
      if (exportItem.status === 'completed') {
        return exportItem;
      }
      if (exportItem.status === 'failed') {
        throw new Error(`Export ${exportId} failed`);
      }
    }

    await new Promise((resolve) => setTimeout(resolve, pollIntervalMs));
  }

  throw new Error(`Export ${exportId} did not complete within ${maxRetries} attempts`);
}

/**
 * Seed a test lead for data rights testing via the E2E test endpoint.
 */
export async function seedTestLead(
  request: APIRequestContext,
  options?: { email?: string; name?: string }
): Promise<{ leadId: string; email: string }> {
  const credentials = defaultAdminCredentials();
  const testEmail = options?.email ?? buildE2eEmail('e2e-data-rights');
  const testName = options?.name ?? 'E2E Data Rights Test Lead';

  const response = await request.post(
    `${credentials.apiBaseUrl}/v1/admin/test/seed-lead`,
    {
      headers: {
        ...getAdminAuthHeaders(credentials),
        'Content-Type': 'application/json',
      },
      data: {
        name: testName,
        email: testEmail,
        phone: '+15555550199',
      },
    }
  );

  if (!response.ok()) {
    const text = await response.text();
    console.error(`Seed lead failed (${response.status()}): ${text}`);
    throw new Error(`Seed lead failed: ${response.status()} - ${text}`);
  }

  const lead = await response.json();
  return { leadId: lead.lead_id, email: lead.email ?? testEmail };
}

/**
 * Process pending deletions via the E2E test endpoint.
 */
export async function processDeletions(
  request: APIRequestContext
): Promise<{ response: Record<string, number>; status: number }> {
  const credentials = defaultAdminCredentials();
  const response = await request.post(
    `${credentials.apiBaseUrl}/v1/admin/test/process-deletions`,
    {
      headers: getAdminAuthHeaders(credentials),
    }
  );

  const status = response.status();
  if (!response.ok()) {
    const text = await response.text();
    // Don't throw if endpoint doesn't exist (404) - test hook may not be enabled
    if (status === 404) {
      console.warn('Test endpoint /v1/admin/test/process-deletions not available');
      return { response: { processed: 0 }, status };
    }
    console.error(`Process deletions failed (${status}): ${text}`);
    throw new Error(`Process deletions failed: ${status} - ${text}`);
  }

  return { response: await response.json(), status };
}

/**
 * Get a lead by ID.
 */
export async function getLead(
  request: APIRequestContext,
  leadId: string
): Promise<{ response: Record<string, unknown> | null; status: number }> {
  const credentials = defaultAdminCredentials();
  const response = await request.get(
    `${credentials.apiBaseUrl}/v1/admin/leads/${leadId}`,
    {
      headers: getAdminAuthHeaders(credentials),
    }
  );

  const status = response.status();
  if (status === 404) {
    return { response: null, status };
  }
  if (!response.ok()) {
    const text = await response.text();
    console.error(`Get lead failed (${status}): ${text}`);
    throw new Error(`Get lead failed: ${status} - ${text}`);
  }

  return { response: await response.json(), status };
}
