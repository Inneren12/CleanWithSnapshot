import { render, screen, fireEvent } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import SummaryCard, { SummaryFieldData } from '../components/SummaryCard';

describe('SummaryCard', () => {
  it('allows editing fields and saving updates', () => {
    const handleSave = vi.fn();
    const fields: SummaryFieldData[] = [
      {
        id: 'address',
        label: 'Address',
        value: '123 Main St',
        type: 'text',
        editable: true,
      },
      {
        id: 'pets',
        label: 'Pets',
        value: false,
        type: 'boolean',
        editable: true,
      },
      {
        id: 'size',
        label: 'Home Size',
        value: 'Medium',
        type: 'text',
      },
    ];

    render(
      <SummaryCard
        title="Booking Summary"
        fields={fields}
        onSave={handleSave}
      />
    );

    fireEvent.click(screen.getByRole('button', { name: 'Edit' }));

    const addressInput = screen.getByDisplayValue('123 Main St');
    fireEvent.change(addressInput, { target: { value: '555 Oak Ave' } });

    const petsCheckbox = screen.getByRole('checkbox');
    fireEvent.click(petsCheckbox);

    fireEvent.click(screen.getByRole('button', { name: 'Apply Changes' }));

    expect(handleSave).toHaveBeenCalledWith({
      address: '555 Oak Ave',
      pets: true,
    });
  });
});
