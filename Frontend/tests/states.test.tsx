import {render, screen} from '@testing-library/react'
import {CollapsibleSection, EmptyState, ErrorState, Freshness, Skeleton} from '../src/components/ui'

test('renders loading empty stale error and collapsed advanced states', () => {
  render(<><Skeleton /><EmptyState title="No holdings" /><Freshness updatedAt={Date.now()} stale /><ErrorState error={new Error('Partial failure')} /><CollapsibleSection title="Advanced controls">Hidden by default</CollapsibleSection></>)
  expect(screen.getByLabelText('Loading')).toBeInTheDocument()
  expect(screen.getByText('No holdings')).toBeInTheDocument()
  expect(screen.getByText(/Stale/)).toBeInTheDocument()
  expect(screen.getByText('Partial failure')).toBeInTheDocument()
  expect(screen.getByText('Advanced controls').closest('details')).not.toHaveAttribute('open')
})
