import { describe, expect, it } from 'vitest'

import { expressionToString, formatUnits } from '@/fsd/entities/model/lib/expressions'
import { simulationToCsv } from '@/fsd/entities/simulation/lib/csv'
import type { SimulationResult } from '@/fsd/entities/simulation/model/types'

describe('model expressions', () => {
  it('renders nested canonical AST without evaluating it', () => {
    expect(
      expressionToString({
        op: 'mul',
        args: [
          { op: 'ref', name: 'population' },
          {
            op: 'sub',
            args: [
              { op: 'lit', value: 1 },
              {
                op: 'div',
                args: [
                  { op: 'ref', name: 'population' },
                  { op: 'ref', name: 'capacity' },
                ],
              },
            ],
          },
        ],
      }),
    ).toBe('(population × (1 − (population / capacity)))')
    expect(
      expressionToString({
        op: 'call',
        name: 'max',
        args: [
          { op: 'lit', value: 0 },
          { op: 'ref', name: 'demand' },
        ],
      }),
    ).toBe('MAX(0, demand)')
    expect(formatUnits({ person: 1, year: -1 })).toBe('person · year^-1')
  })
})

describe('simulation CSV', () => {
  it('exports every variable and escapes labels', () => {
    const result: SimulationResult = {
      schema_version: '2.0',
      model_id: 'population',
      model_hash: 'a'.repeat(64),
      time: [0, 1],
      variables: { population: [100, 105], 'growth, yearly': [10, 5] },
      requested_engine: 'auto',
      engine: 'pysd',
      requested_method: 'euler',
      integration_method: 'euler',
      time_step: 1,
      saveper: 1,
      fallback_reason: null,
      warnings: [],
    }
    expect(simulationToCsv(result)).toBe('time,population,"growth, yearly"\n0,100,10\n1,105,5\n')
  })
})
