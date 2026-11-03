import type { SDVariable } from '../model/types'

type Expression = Record<string, unknown>

function identifier(value: unknown): string {
  const name = String(value)
  return `\\mathit{${name.replaceAll('_', '\\_')}}`
}

function group(value: string): string {
  return `\\left(${value}\\right)`
}

function args(expression: Expression): unknown[] {
  return Array.isArray(expression.args) ? expression.args : []
}

const binaryOperators: Record<string, string> = {
  add: '+',
  sub: '-',
  mul: '\\cdot',
  mod: '\\bmod',
  lt: '<',
  le: '\\leq',
  gt: '>',
  ge: '\\geq',
  eq: '=',
  ne: '\\neq',
  and: '\\land',
  or: '\\lor',
}

export function expressionToLatex(value: unknown): string {
  if (value === null || value === undefined) return '\\text{—}'
  if (typeof value === 'number') return String(value)
  if (typeof value === 'boolean') return value ? '\\mathrm{true}' : '\\mathrm{false}'
  if (typeof value !== 'object') return `\\text{${String(value)}}`
  const expression = value as Expression
  const op = expression.op
  if (op === 'lit') return expressionToLatex(expression.value)
  if (op === 'ref') return identifier(expression.name)
  if (op === 'time') return 't'
  if (op === 'array') {
    return `\\begin{bmatrix}${(expression.values as unknown[])
      .map(expressionToLatex)
      .join(' & ')}\\end{bmatrix}`
  }
  if (op === 'lookup') {
    return `\\operatorname{LOOKUP}_{\\text{${String(expression.table)}}}${group(expressionToLatex(expression.arg))}`
  }
  if (op === 'if') {
    return `\\begin{cases}${expressionToLatex(expression.then)}, & ${expressionToLatex(expression.condition)}\\\\${expressionToLatex(expression.otherwise)}, & \\text{otherwise}\\end{cases}`
  }
  if (op === 'neg' || op === 'pos' || op === 'not') {
    const prefix = op === 'neg' ? '-' : op === 'pos' ? '+' : '\\neg '
    return `${prefix}${group(expressionToLatex(expression.arg))}`
  }
  if (op === 'call') {
    const name = String(expression.name)
    const values = args(expression).map(expressionToLatex)
    if (name === 'if_then_else' && values.length === 3) {
      return `\\begin{cases}${values[1]}, & ${values[0]}\\\\${values[2]}, & \\text{otherwise}\\end{cases}`
    }
    if (name === 'exp' && values.length === 1) return `e^{${values[0]}}`
    if ((name === 'power' || name === 'pow') && values.length === 2) {
      return `${group(values[0])}^{${values[1]}}`
    }
    if (name === 'sqrt' && values.length === 1) return `\\sqrt{${values[0]}}`
    if (name === 'abs' && values.length === 1) return `\\left|${values[0]}\\right|`
    if (name === 'log' && values.length === 1) return `\\ln${group(values[0])}`
    if (name === 'log10' && values.length === 1) return `\\log_{10}${group(values[0])}`
    if (['sin', 'cos', 'tan', 'min', 'max'].includes(name)) {
      return `\\${name}${group(values.join(', '))}`
    }
    return `\\operatorname{${name.replaceAll('_', '\\_')}}${group(values.join(', '))}`
  }
  const values = args(expression)
  if (op === 'div' && values.length === 2) {
    return `\\frac{${expressionToLatex(values[0])}}{${expressionToLatex(values[1])}}`
  }
  if (op === 'pow' && values.length === 2) {
    return `${group(expressionToLatex(values[0]))}^{${expressionToLatex(values[1])}}`
  }
  if (typeof op === 'string' && values.length > 0) {
    const operator = binaryOperators[op] ?? op
    return group(values.map(expressionToLatex).join(` ${operator} `))
  }
  return `\\texttt{${JSON.stringify(value)}}`
}

function endpointId(value: unknown): string | null {
  if (!value || typeof value !== 'object') return null
  const id = (value as Record<string, unknown>).id
  return typeof id === 'string' ? id : null
}

function stockDerivative(variable: SDVariable, variables: SDVariable[]): string {
  if (variable.derivative) return expressionToLatex(variable.derivative)
  const terms: string[] = []
  for (const flow of variables.filter((candidate) => candidate.kind === 'flow')) {
    if (endpointId(flow.target) === variable.id) {
      terms.push(`${terms.length ? ' + ' : ''}${identifier(flow.id)}`)
    }
    if (endpointId(flow.source) === variable.id) {
      terms.push(`${terms.length ? ' - ' : ' - '}${identifier(flow.id)}`)
    }
  }
  return terms.join('') || '0'
}

export function variableEquationLatex(variable: SDVariable, variables: SDVariable[]): string {
  if (variable.kind === 'stock') {
    return `\\frac{d\\,${identifier(variable.id)}}{dt} = ${stockDerivative(variable, variables)}`
  }
  return `${identifier(variable.id)} = ${expressionToLatex(variable.expression)}`
}

export function stockInitialLatex(variable: SDVariable): string {
  return `${identifier(variable.id)}(0) = ${expressionToLatex(variable.initial)}`
}

function unitName(name: string): string {
  return `\\mathrm{${name.replaceAll('_', '\\_')}}`
}

function unitPower(name: string, exponent: number): string {
  const unit = unitName(name)
  return exponent === 1 ? unit : `${unit}^{${exponent}}`
}

export function unitsToLatex(units: Record<string, number> | null | undefined): string {
  if (!units) return '\\text{—}'
  const entries = Object.entries(units).filter(([, exponent]) => exponent !== 0)
  if (entries.length === 0) return '\\text{dimensionless}'
  const numerator = entries.filter(([, exponent]) => exponent > 0)
  const denominator = entries.filter(([, exponent]) => exponent < 0)
  if (denominator.length === 0) {
    return numerator.map(([name, exponent]) => unitPower(name, exponent)).join(' \\cdot ')
  }
  const top = numerator.length
    ? numerator.map(([name, exponent]) => unitPower(name, exponent)).join(' \\cdot ')
    : '1'
  const bottom = denominator
    .map(([name, exponent]) => unitPower(name, Math.abs(exponent)))
    .join(' \\cdot ')
  return `\\frac{${top}}{${bottom}}`
}
