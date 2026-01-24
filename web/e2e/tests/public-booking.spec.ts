import { expect, test } from '@playwright/test';

test.describe('Public booking flow', () => {
  test('request estimate and reach booking details', async ({ page }) => {
    await page.goto('/');

    const chatInput = page.getByPlaceholder('Type your message...');
    await expect(chatInput).toBeEnabled();

    await chatInput.fill('2 bed 1 bath standard cleaning');
    await page.getByRole('button', { name: 'Send' }).click();

    // Wait for bot response with increased timeout (CI can be slow)
    await expect(page.getByTestId('bot-message').first()).toBeVisible({
      timeout: 30000,
    });

    // Wait for "Ready to book" pill to appear (indicates estimate is ready)
    await expect(page.getByTestId('ready-to-book-pill')).toBeVisible({
      timeout: 30000,
    });

    // Verify booking details section appears
    await expect(
      page.getByRole('heading', { name: 'Share details to confirm your booking' })
    ).toBeVisible({ timeout: 10000 });
  });
});
