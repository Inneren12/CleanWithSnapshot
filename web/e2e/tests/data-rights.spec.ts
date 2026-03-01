import { expect, test } from '@playwright/test';

import {
  defaultAdminCredentials,
  seedAdminStorage,
  verifyAdminCredentials,
} from './helpers/adminAuth';
import {
  downloadDataExport,
  getLead,
  listDataExports,
  processDataExports,
  processDeletions,
  requestDataDeletion,
  requestDataExportAsync,
  requestDataExportSync,
  runRetentionCleanup,
  setSaasAuthWorkerIndex,
  seedTestLead,
  waitForExportCompletion,
} from './helpers/dataRightsApi';

test.describe('GDPR Data Rights', () => {
  test.beforeEach(async ({ page, request }, testInfo) => {
    const admin = defaultAdminCredentials();
    setSaasAuthWorkerIndex(testInfo.workerIndex);
    await verifyAdminCredentials(request, admin);
    await seedAdminStorage(page, admin);
  });

  test.describe('Data Export - Synchronous Admin Flow', () => {
    test('exports data for a lead by lead_id', async ({ request }) => {
      // Seed a test lead
      const { leadId, email } = await seedTestLead(request);

      // Request synchronous export
      const { response, status } = await requestDataExportSync(request, {
        leadId,
      });

      expect(status).toBe(200);
      expect(response.leads).toBeDefined();
      expect(response.leads.length).toBeGreaterThanOrEqual(1);
      expect(response.bookings).toBeDefined();
      expect(response.invoices).toBeDefined();
      expect(response.payments).toBeDefined();
      expect(response.photos).toBeDefined();

      // Verify the exported lead matches
      const exportedLead = response.leads.find(
        (l: Record<string, unknown>) => l.lead_id === leadId
      );
      expect(exportedLead).toBeDefined();
      expect(exportedLead?.email).toBe(email);
    });

    test('exports data for a lead by email', async ({ request }) => {
      // Seed a test lead
      const { leadId, email } = await seedTestLead(request);

      // Request synchronous export by email
      const { response, status } = await requestDataExportSync(request, {
        email,
      });

      expect(status).toBe(200);
      expect(response.leads).toBeDefined();
      expect(response.leads.length).toBeGreaterThanOrEqual(1);

      // Verify the exported lead matches
      const exportedLead = response.leads.find(
        (l: Record<string, unknown>) => l.lead_id === leadId
      );
      expect(exportedLead).toBeDefined();
    });

    test('returns 404 for non-existent lead', async ({ request }) => {
      try {
        await requestDataExportSync(request, {
          leadId: 'non-existent-lead-id-12345',
        });
        // Should not reach here
        expect(true).toBe(false);
      } catch (error) {
        expect((error as Error).message).toContain('404');
      }
    });
  });

  test.describe('Data Export - Async Flow with Job Processing', () => {
    test('creates export request and completes via job processing', async ({
      request,
    }) => {
      console.log('[TEST START] Creating test lead...');
      const { leadId, email } = await seedTestLead(request);
      console.log('[TEST] Lead created:', leadId);

      console.log('[TEST] Requesting async export...');
      let exportResponse;
      try {
        exportResponse = await requestDataExportAsync(request, { leadId });
        console.log('[TEST] Async export SUCCESS:', exportResponse);
      } catch (error: any) {
        console.error('[TEST ERROR] Async export FAILED');
        console.error('[TEST ERROR] Error name:', error.name);
        console.error('[TEST ERROR] Error message:', error.message);
        console.error('[TEST ERROR] Error stack:', error.stack);

        // If it's an HTTP error from Playwright
        if (error.response) {
          const status = error.response.status();
          const body = await error.response.text();
          console.error('[TEST ERROR] HTTP Status:', status);
          console.error('[TEST ERROR] Response body:', body);
          console.error('[TEST ERROR] Response headers:', await error.response.allHeaders());
        }

        throw error;
      }

      const { export_id } = exportResponse.response;
      console.log('[TEST] Export ID:', export_id);

      console.log('[TEST] Waiting for export completion...');
      const completedExport = await waitForExportCompletion(request, export_id, {
        leadId,
        email,
      });
      console.log('[TEST] Export completed:', completedExport);

      expect(completedExport.status).toBe('completed');
      expect(completedExport.subject_id).toBe(leadId);
    });

    test('lists export requests for a subject', async ({ request }) => {
      // Seed a test lead
      const { leadId, email } = await seedTestLead(request);

      // Create an export request
      await requestDataExportAsync(request, { leadId, email });

      // Process to complete
      await processDataExports(request);

      // List exports
      const { response: listResponse } = await listDataExports(request, {
        leadId,
        email,
      });

      expect(listResponse.items.length).toBeGreaterThanOrEqual(1);
      expect(listResponse.total).toBeGreaterThanOrEqual(1);

      // Find our export
      const ourExport = listResponse.items.find((item) =>
        item.status === 'completed' || item.status === 'pending'
      );
      expect(ourExport).toBeDefined();
    });
  });

  test.describe('Data Export Download', () => {
    test('downloads completed export', async ({ request }) => {
      // Seed a test lead
      const { leadId, email } = await seedTestLead(request);

      // Create and process export
      const { response: exportRequest } = await requestDataExportAsync(
        request,
        { leadId, email }
      );
      await processDataExports(request);

      // Wait for completion
      await waitForExportCompletion(request, exportRequest.export_id, {
        leadId,
        email,
        maxRetries: 10,
        pollIntervalMs: 500,
      });

      // Download the export
      const { body, status, contentType } = await downloadDataExport(
        request,
        exportRequest.export_id
      );

      // Should be either 200 (direct file) or 307 (redirect to signed URL)
      expect([200, 307]).toContain(status);

      if (status === 200 && body) {
        // Verify body is non-empty JSON
        expect(body.length).toBeGreaterThan(0);
        expect(contentType).toContain('application/json');

        // Parse and verify structure
        const exportData = JSON.parse(body.toString());
        expect(exportData.export_id).toBe(exportRequest.export_id);
        expect(exportData.data).toBeDefined();
        expect(exportData.data.leads).toBeDefined();
      }
    });

    test('returns 404 for non-existent export', async ({ request }) => {
      try {
        await downloadDataExport(request, '00000000-0000-0000-0000-000000000000');
        // Should not reach here
        expect(true).toBe(false);
      } catch (error) {
        expect((error as Error).message).toContain('404');
      }
    });
  });

  test.describe('Data Deletion Flow', () => {
    test('creates deletion request for a lead', async ({ request }) => {
      // Seed a test lead
      const { leadId } = await seedTestLead(request);

      // Request deletion
      const { response: deletionResponse, status } = await requestDataDeletion(
        request,
        {
          leadId,
          reason: 'E2E test - GDPR deletion request',
        }
      );

      expect(status).toBe(200);
      expect(deletionResponse.request_id).toBeDefined();
      expect(deletionResponse.status).toBe('pending');
      expect(deletionResponse.matched_leads).toBe(1);
      expect(deletionResponse.pending_deletions).toBe(1);
    });

    test('processes deletion and anonymizes lead data', async ({ request }) => {
      // Seed a test lead
      const { leadId, email } = await seedTestLead(request, {
        name: 'Deletion Test Lead',
        email: `delete-test-${Date.now()}-${Math.random().toString(16).slice(2)}@example.com`,
      });

      // Verify lead exists before deletion
      const { response: leadBefore } = await getLead(request, leadId);
      expect(leadBefore).not.toBeNull();
      expect(leadBefore?.email).toBe(email);
      expect(leadBefore?.name).toBe('Deletion Test Lead');

      // Request deletion
      const { response: deletionResponse } = await requestDataDeletion(
        request,
        {
          leadId,
          reason: 'E2E test - GDPR deletion request',
        }
      );

      expect(deletionResponse.status).toBe('pending');

      // Process deletions (via test hook or cleanup endpoint)
      try {
        await processDeletions(request);
      } catch {
        // Fallback to retention cleanup if test hook not available
        await runRetentionCleanup(request);
      }

      // Fix: GDPR deletion hard-deletes the lead if there are no FK constraints (like bookings), instead of anonymizing it.
      // Verify lead is anonymized or hard-deleted
      const { response: leadAfter } = await getLead(request, leadId);
      if (leadAfter) {
        expect(leadAfter.name).toBe('[deleted]');
        expect(leadAfter.email).toBeNull();
        expect(leadAfter.phone).toBe('[deleted]');
        expect(leadAfter.deleted_at).toBeDefined();
      } else {
        expect(leadAfter).toBeNull();
      }
    });

    test('returns 404 for non-existent lead deletion request', async ({
      request,
    }) => {
      try {
        await requestDataDeletion(request, {
          leadId: 'non-existent-lead-id-12345',
          reason: 'E2E test',
        });
        // Should not reach here
        expect(true).toBe(false);
      } catch (error) {
        expect((error as Error).message).toContain('404');
      }
    });
  });

  test.describe('Data Rights - Full GDPR Workflow', () => {
    test('complete export-then-delete workflow', async ({ request }) => {
      // Step 1: Seed a test lead
      const { leadId, email } = await seedTestLead(request, {
        name: 'GDPR Workflow Test Lead',
      });

      // Step 2: Export the data first (as per GDPR best practice)
      const { response: exportRequest } = await requestDataExportAsync(
        request,
        { leadId, email }
      );

      // Step 3: Process and wait for export
      await processDataExports(request);
      const completedExport = await waitForExportCompletion(
        request,
        exportRequest.export_id,
        {
          leadId,
          email,
          maxRetries: 10,
          pollIntervalMs: 500,
        }
      );

      expect(completedExport.status).toBe('completed');

      // Step 4: Verify we can download the export
      const { status: downloadStatus } = await downloadDataExport(
        request,
        exportRequest.export_id
      );
      expect([200, 307]).toContain(downloadStatus);

      // Step 5: Now request deletion
      const { response: deletionResponse } = await requestDataDeletion(
        request,
        {
          leadId,
          reason: 'E2E test - complete GDPR workflow',
        }
      );

      expect(deletionResponse.status).toBe('pending');

      // Step 6: Process deletion
      try {
        await processDeletions(request);
      } catch {
        await runRetentionCleanup(request);
      }

      // Fix: GDPR deletion hard-deletes the lead if there are no FK constraints, so expect it to potentially be null.
      // Step 7: Verify lead is anonymized or hard-deleted
      const { response: leadAfter } = await getLead(request, leadId);
      if (leadAfter) {
        expect(leadAfter.deleted_at).toBeDefined();
        expect(leadAfter.email).toBeNull();
      } else {
        expect(leadAfter).toBeNull();
      }
    });
  });

  test.describe('Data Rights - Error Handling', () => {
    test('handles export request with missing parameters gracefully', async ({
      request,
    }) => {
      // Admin export requires lead_id or email
      try {
        await requestDataExportSync(request, {});
        expect(true).toBe(false); // Should not reach here
      } catch (error) {
        // Should fail with validation error
        // Fix: Suppressed misleading console.error from dataRightsApi.ts
        expect((error as Error).message).toMatch(/400|422/);
      }
    });

    test('handles deletion request with missing parameters gracefully', async ({
      request,
    }) => {
      // Deletion requires lead_id or email
      try {
        await requestDataDeletion(request, {});
        expect(true).toBe(false); // Should not reach here
      } catch (error) {
        // Should fail with validation error
        expect((error as Error).message).toMatch(/400|422/);
      }
    });
  });
});
