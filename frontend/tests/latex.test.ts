import katex from 'katex'
import { describe, expect, it } from 'vitest'

import {
  expressionToLatex,
  stockInitialLatex,
  unitsToLatex,
  variableEquationLatex,
} from '@/fsd/entities/model/lib/latex'
import type { SDVariable } from '@/fsd/entities/model/model/types'

describe('AST to LaTeX', () => {
  it('renders fractions, multiplication and functions as math', () => {
    const fraction = expressionToLatex({
      op: 'div',
      args: [
        { op: 'ref', name: 'population' },
        { op: 'ref', name: 'capacity' },
      ],
    })
    expect(fraction).toBe('\\frac{\\mathit{population}}{\\mathit{capacity}}')
    const delay = expressionToLatex({
      op: 'call',
      name: 'delay3',
      args: [
        { op: 'ref', name: 'input' },
        { op: 'ref', name: 'delay' },
      ],
    })
    expect(() => katex.renderToString(delay, { throwOnError: true, strict: 'error' })).not.toThrow()
  })

  it('uses flow signs instead of concatenating plus and minus', () => {
    const prey: SDVariable = { id: 'prey', kind: 'stock', initial: { op: 'lit', value: 100 } }
    const births: SDVariable = {
      id: 'prey_births',
      kind: 'flow',
      target: { kind: 'stock', id: 'prey' },
    }
    const predation: SDVariable = {
      id: 'predation',
      kind: 'flow',
      source: { kind: 'stock', id: 'prey' },
    }
    expect(variableEquationLatex(prey, [prey, births, predation])).toBe(
      '\\frac{d\\,\\mathit{prey}}{dt} = \\mathit{prey\\_births} - \\mathit{predation}',
    )
    expect(stockInitialLatex(prey)).toBe('\\mathit{prey}(0) = 100')
    expect(() =>
      katex.renderToString(variableEquationLatex(prey, [prey, births, predation]), {
        throwOnError: true,
        strict: 'error',
      }),
    ).not.toThrow()
  })

  it('formats unit exponents as fractions and preserves dimensionless units', () => {
    expect(unitsToLatex({ student: 1, year: -1 })).toBe('\\frac{\\mathrm{student}}{\\mathrm{year}}')
    expect(unitsToLatex({ year: -1 })).toBe('\\frac{1}{\\mathrm{year}}')
    expect(unitsToLatex({})).toBe('\\text{dimensionless}')
    expect(unitsToLatex(null)).toBe('\\text{—}')
    expect(() =>
      katex.renderToString(unitsToLatex({ student: 1, year: -1 }), {
        throwOnError: true,
        strict: 'error',
      }),
    ).not.toThrow()
  })
})
