import {render, screen} from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import {MemoryRouter} from 'react-router-dom'
import {EmptyState, ErrorState, Freshness, Skeleton, TerminalPanel} from '../src/components/ui'
import {useWorkspacePreferences} from '../src/stores/workspacePreferences'

test('renders loading empty stale error and collapsed advanced states', async () => {
  useWorkspacePreferences.getState().resetWorkspace()
  const user = userEvent.setup()
  render(<MemoryRouter initialEntries={['/states']}><Skeleton /><EmptyState title="No holdings" /><Freshness updatedAt={Date.now()} stale /><ErrorState error={new Error('Partial failure')} /><TerminalPanel id="advanced" title="Advanced controls" defaultOpen={false}>Hidden by default</TerminalPanel></MemoryRouter>)
  expect(screen.getByLabelText('Loading')).toBeInTheDocument()
  expect(screen.getByText('No holdings')).toBeInTheDocument()
  expect(screen.getByText(/Stale/)).toBeInTheDocument()
  expect(screen.getByText('Partial failure')).toBeInTheDocument()
  const toggle = screen.getByRole('button', {name: /Advanced controls/})
  expect(toggle).toHaveAttribute('aria-expanded', 'false')
  expect(screen.getByText('Hidden by default').closest('.panel-content')).toHaveAttribute('hidden')
  await user.click(toggle)
  expect(toggle).toHaveAttribute('aria-expanded', 'true')
  expect(localStorage.getItem('finflock-workspace-v1')).toContain('/states:advanced')
})
