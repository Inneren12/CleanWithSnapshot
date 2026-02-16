import { test, expect } from 'vitest';
import { isLeadFormComplete } from '../app/bookingValidation';

test('Empty required fields should not be considered complete', () => {
  expect(
    isLeadFormComplete({
      name: '',
      phone: '',
      address: '',
      selectedSlot: null,
    })
  ).toBe(false);
});

test('Valid required fields and slot should be considered complete', () => {
  expect(
    isLeadFormComplete({
      name: 'Jamie Doe',
      phone: '7805551234',
      address: '123 Jasper Ave',
      selectedSlot: '2025-02-10T19:00:00.000Z',
    })
  ).toBe(true);
});
