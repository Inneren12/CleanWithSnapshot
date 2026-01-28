import { render, screen, fireEvent } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import PrimaryCTA from '../components/PrimaryCTA';

describe('PrimaryCTA', () => {
  it('renders the label and triggers clicks', () => {
    const handleClick = vi.fn();

    render(
      <PrimaryCTA
        label="Confirm Booking"
        onClick={handleClick}
      />
    );

    const button = screen.getByRole('button', { name: 'Confirm Booking' });
    fireEvent.click(button);

    expect(handleClick).toHaveBeenCalledTimes(1);
  });

  it('shows loading state and disables the button', () => {
    const handleClick = vi.fn();

    render(
      <PrimaryCTA
        label="Confirm Booking"
        onClick={handleClick}
        loading
      />
    );

    const button = screen.getByRole('button', { name: /loading|confirm booking/i });
    expect(button).toBeDisabled();
    expect(screen.getByText(/loading/i)).toBeInTheDocument();
  });
});
