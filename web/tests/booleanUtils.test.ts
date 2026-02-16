import { describe, it, expect } from 'vitest';
import { formatBooleanLabel, normalizeBooleanValue } from '../components/booleanUtils';

describe('booleanUtils', () => {
  describe('normalizeBooleanValue', () => {
    it('should return the same boolean value when input is a boolean', () => {
      expect(normalizeBooleanValue(true)).toBe(true);
      expect(normalizeBooleanValue(false)).toBe(false);
    });

    it('should return false for nullish values', () => {
      expect(normalizeBooleanValue(null)).toBe(false);
      expect(normalizeBooleanValue(undefined)).toBe(false);
    });

    it('should return false for string values, even if they look like booleans', () => {
      expect(normalizeBooleanValue('true')).toBe(false);
      expect(normalizeBooleanValue('false')).toBe(false);
      expect(normalizeBooleanValue('')).toBe(false);
    });

    it('should return false for numeric values', () => {
      expect(normalizeBooleanValue(1)).toBe(false);
      expect(normalizeBooleanValue(0)).toBe(false);
      expect(normalizeBooleanValue(-1)).toBe(false);
      expect(normalizeBooleanValue(NaN)).toBe(false);
    });

    it('should return false for objects and arrays', () => {
      expect(normalizeBooleanValue({})).toBe(false);
      expect(normalizeBooleanValue([])).toBe(false);
    });
  });

  describe('formatBooleanLabel', () => {
    it('should return "Yes" for true', () => {
      expect(formatBooleanLabel(true)).toBe('Yes');
    });

    it('should return "No" for false', () => {
      expect(formatBooleanLabel(false)).toBe('No');
    });

    it('should return "—" for non-boolean values', () => {
      expect(formatBooleanLabel(null)).toBe('—');
      expect(formatBooleanLabel(undefined)).toBe('—');
      expect(formatBooleanLabel('true')).toBe('—');
      expect(formatBooleanLabel(1)).toBe('—');
      expect(formatBooleanLabel({})).toBe('—');
      expect(formatBooleanLabel([])).toBe('—');
    });
  });
});
