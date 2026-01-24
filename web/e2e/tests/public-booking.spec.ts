import { expect, test } from '@playwright/test';

test.describe('Public booking flow', () => {
  test('request estimate and reach booking details', async ({ page }) => {
    await page.goto('/');

    // Verify E2E mode is active (deterministic bot response enabled)
    await expect(page.getByTestId('e2e-mode-on')).toBeAttached();

    const chatInput = page.getByPlaceholder('Type your message...');
    await expect(chatInput).toBeEnabled();

    await chatInput.fill('2 bed 1 bath standard cleaning');
    await page.getByRole('button', { name: 'Send' }).click();

    // Wait for bot response (E2E mode: fast deterministic response, ~500ms)
    // Timeout increased for CI runner slowness
    await expect(page.getByTestId('bot-message').first()).toBeVisible({
      timeout: 10000,
    });

    // Wait for "Ready to book" pill to appear (indicates estimate is ready)
    await expect(page.getByTestId('ready-to-book-pill')).toBeVisible({
      timeout: 5000,
    });

    // Verify booking details section appears
    await expect(
      page.getByRole('heading', { name: 'Share details to confirm your booking' })
    ).toBeVisible({ timeout: 10000 });
  });
});
