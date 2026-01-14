import assert from 'node:assert';
import { isLeadFormComplete } from '../app/bookingValidation';

assert.strictEqual(
  isLeadFormComplete({
    name: '',
    phone: '',
    address: '',
    selectedSlot: null,
  }),
  false,
  'Empty required fields should not be considered complete.'
);

assert.strictEqual(
  isLeadFormComplete({
    name: 'Jamie Doe',
    phone: '7805551234',
    address: '123 Jasper Ave',
    selectedSlot: '2025-02-10T19:00:00.000Z',
  }),
  true,
  'Valid required fields and slot should be considered complete.'
);

console.log('Booking validation tests passed.');
