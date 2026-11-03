import type { SimulationResult } from '../model/types'

function cell(value: string | number): string {
  const text = String(value)
  return /[",\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text
}

export function simulationToCsv(result: SimulationResult): string {
  const names = Object.keys(result.variables)
  const rows = [['time', ...names].map(cell).join(',')]
  result.time.forEach((time, index) => {
    rows.push([time, ...names.map((name) => result.variables[name][index])].map(cell).join(','))
  })
  return `${rows.join('\n')}\n`
}
