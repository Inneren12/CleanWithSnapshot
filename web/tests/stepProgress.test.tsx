import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import StepProgress from '../components/StepProgress';

describe('StepProgress', () => {
  it('shows the step and remaining count with progress width', () => {
    const { container } = render(
      <StepProgress
        currentStep={2}
        totalSteps={5}
        remaining={3}
      />
    );

    expect(screen.getByText('Step 2 of 5')).toBeInTheDocument();
    expect(screen.getByText('• 3 remaining')).toBeInTheDocument();

    const progressFill = container.querySelector('.step-progress-fill');
    expect(progressFill).toHaveStyle({ width: '40%' });
  });
});
