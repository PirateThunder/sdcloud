import type { SDVariable } from '../model/types'

type Expression = Record<string, unknown>

const operators: Record<string, string> = {
  add: '+',
  sub: '−',
  mul: '×',
  div: '/',
  pow: '^',
  mod: 'mod',
  lt: '<',
  le: '≤',
  gt: '>',
  ge: '≥',
  eq: '=',
  ne: '≠',
  and: 'and',
  or: 'or',
}

export function expressionToString(value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  if (typeof value !== 'object') return String(value)
  const expression = value as Expression
  const op = expression.op
  if (op === 'lit') return String(expression.value)
  if (op === 'ref') return String(expression.name)
  if (op === 'time') return 'TIME'
  if (op === 'array')
    return `[${(expression.values as unknown[]).map(expressionToString).join(', ')}]`
  if (op === 'lookup') return `LOOKUP(${expression.table}, ${expressionToString(expression.arg)})`
  if (op === 'if') {
    return `IF(${expressionToString(expression.condition)}, ${expressionToString(expression.then)}, ${expressionToString(expression.otherwise)})`
  }
  if (op === 'neg' || op === 'pos' || op === 'not') {
    const prefix = op === 'neg' ? '−' : op === 'pos' ? '+' : 'not '
    return `${prefix}${expressionToString(expression.arg)}`
  }
  if (op === 'call') {
    const args = (expression.args as unknown[]).map(expressionToString).join(', ')
    return `${String(expression.name).toUpperCase()}(${args})`
  }
  const args = expression.args
  if (typeof op === 'string' && Array.isArray(args)) {
    const operator = operators[op] ?? op
    return `(${args.map(expressionToString).join(` ${operator} `)})`
  }
  return JSON.stringify(value)
}

function endpointId(value: unknown): string | null {
  if (!value || typeof value !== 'object') return null
  const id = (value as Record<string, unknown>).id
  return typeof id === 'string' ? id : null
}

export function variableEquation(variable: SDVariable, variables: SDVariable[]): string {
  if (variable.kind === 'stock') {
    const derivative = variable.derivative
      ? expressionToString(variable.derivative)
      : variables
          .filter((candidate) => candidate.kind === 'flow')
          .flatMap((flow) => {
            const parts = []
            if (endpointId(flow.target) === variable.id) parts.push(flow.id)
            if (endpointId(flow.source) === variable.id) parts.push(`−${flow.id}`)
            return parts
          })
          .join(' + ') || '0'
    return `d(${variable.id})/dt = ${derivative}`
  }
  return `${variable.id} = ${expressionToString(variable.expression)}`
}

export function formatUnits(units: Record<string, number> | null | undefined): string {
  if (!units || Object.keys(units).length === 0) return 'dimensionless'
  return Object.entries(units)
    .map(([name, exponent]) => (exponent === 1 ? name : `${name}^${exponent}`))
    .join(' · ')
}
