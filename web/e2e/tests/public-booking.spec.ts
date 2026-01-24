import { expect, test } from '@playwright/test';

test.describe('Public booking flow', () => {
  test('request estimate and reach booking details', async ({ page }) => {
    await page.goto('/');

    const e2eMarker = page.getByTestId('e2e-mode-on');
    if ((await e2eMarker.count()) > 0) {
      await expect(e2eMarker).toBeVisible();
    }

    const chatInput = page.getByPlaceholder('Type your message...');
    await expect(chatInput).toBeEnabled();

    await chatInput.fill('2 bed 1 bath standard cleaning');
    await page.getByRole('button', { name: 'Send' }).click();

    await expect(page.getByTestId('bot-message').first()).toBeVisible();
    await expect(page.getByText('Ready to book', { exact: true })).toBeVisible();
    await expect(
      page.getByRole('heading', { name: 'Share details to confirm your booking' })
    ).toBeVisible();
  });
});
