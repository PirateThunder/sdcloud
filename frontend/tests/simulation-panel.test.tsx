import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import type { ModelVersionDetail } from '@/fsd/entities/model/model/types'
import { createSimulation, listSimulations } from '@/fsd/entities/simulation/api/simulation-api'
import { SimulationPanel } from '@/fsd/features/simulation-run/simulation-panel'

vi.mock('@/fsd/entities/simulation/api/simulation-api', () => ({
  createSimulation: vi.fn(),
  listSimulations: vi.fn(),
  retrySimulation: vi.fn(),
}))
vi.mock('@/fsd/features/simulation-run/use-simulation', () => ({
  useSimulation: () => ({ data: undefined, isPending: false }),
}))
vi.mock('@/fsd/features/simulation-run/simulation-chart', () => ({
  SimulationChart: () => null,
}))

const version = {
  id: 'version-1',
  model_id: 'model-1',
  generation_id: 'generation-1',
  version: 1,
  name: 'Population',
  model_hash: 'a'.repeat(64),
  created_at: '2026-01-01T00:00:00Z',
  available_exports: ['python'],
  document: {
    schema_version: '2.0',
    id: 'population',
    name: 'Population',
    description: 'Test',
    time: { unit: 'year', initial_time: 0, final_time: 1, time_step: 0.25, saveper: 0.25 },
    variables: [
      { id: 'population', kind: 'stock', initial: { op: 'lit', value: 100 }, units: { person: 1 } },
      {
        id: 'growth_rate',
        kind: 'constant',
        expression: { op: 'lit', value: 0.1 },
        units: { year: -1 },
      },
    ],
  },
} as ModelVersionDetail

describe('SimulationPanel', () => {
  it('submits with blank overrides and preserves model defaults', async () => {
    vi.mocked(listSimulations).mockResolvedValue([])
    vi.mocked(createSimulation).mockResolvedValue({ id: 'simulation-1' } as never)
    const user = userEvent.setup()
    render(
      <QueryClientProvider client={new QueryClient()}>
        <SimulationPanel version={version} />
      </QueryClientProvider>,
    )
    await user.click(screen.getByRole('button', { name: 'Запустить симуляцию' }))
    await waitFor(() => expect(createSimulation).toHaveBeenCalledOnce())
    const [versionId, parameters] = vi.mocked(createSimulation).mock.calls[0]
    expect(versionId).toBe('version-1')
    expect(parameters).toMatchObject({
      final_time: 1,
      time_step: 0.25,
      parameters: {},
      stock_initial: {},
    })
  })
})
