'use client'

import { Download } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import { simulationToCsv } from '@/fsd/entities/simulation/lib/csv'
import type { SimulationResult } from '@/fsd/entities/simulation/model/types'
import { formatNumber } from '@/fsd/shared/lib/utils'
import { Badge } from '@/fsd/shared/ui/badge'
import { Button } from '@/fsd/shared/ui/button'
import { Card } from '@/fsd/shared/ui/card'
import { Select } from '@/fsd/shared/ui/select'

export function SimulationChart({ result }: { result: SimulationResult }) {
  const names = useMemo(() => Object.keys(result.variables), [result.variables])
  const [selected, setSelected] = useState(names[0] ?? '')
  useEffect(() => {
    if (!names.includes(selected)) setSelected(names[0] ?? '')
  }, [names, selected])
  const values = selected ? result.variables[selected] : []
  const data = result.time.map((time, index) => ({ time, value: values[index] }))
  const final = values.at(-1)
  const minimum = values.length ? Math.min(...values) : 0
  const maximum = values.length ? Math.max(...values) : 0

  const downloadCsv = () => {
    const blob = new Blob([simulationToCsv(result)], { type: 'text/csv;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = 'simulation.csv'
    anchor.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap gap-2">
          <Badge className="bg-accent text-accent-foreground">{result.engine}</Badge>
          <Badge>{result.integration_method}</Badge>
          {result.fallback_reason && (
            <Badge className="bg-destructive/10 text-destructive">fallback</Badge>
          )}
        </div>
        <Button size="sm" variant="outline" onClick={downloadCsv}>
          <Download /> CSV
        </Button>
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <label htmlFor="simulation-variable" className="text-xs font-medium text-muted-foreground">
          Переменная
        </label>
        <Select
          id="simulation-variable"
          value={selected}
          onChange={(event) => setSelected(event.target.value)}
          className="max-w-full"
        >
          {names.map((name) => (
            <option key={name} value={name}>
              {name}
            </option>
          ))}
        </Select>
      </div>
      <div className="h-[360px] w-full rounded-xl border border-border bg-card p-3">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 16, right: 20, bottom: 8, left: 8 }}>
            <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />
            <XAxis
              dataKey="time"
              tick={{ fill: 'var(--muted-foreground)', fontSize: 11 }}
              tickLine={false}
              axisLine={{ stroke: 'var(--border)' }}
            />
            <YAxis
              domain={['auto', 'auto']}
              tick={{ fill: 'var(--muted-foreground)', fontSize: 11 }}
              tickFormatter={(value: number) => formatNumber(value)}
              tickLine={false}
              axisLine={false}
              width={70}
            />
            <Tooltip
              formatter={(value) => [
                typeof value === 'number' ? formatNumber(value) : String(value),
                selected,
              ]}
              labelFormatter={(time) => `t = ${time}`}
              contentStyle={{
                background: 'var(--card)',
                border: '1px solid var(--border)',
                borderRadius: 10,
                color: 'var(--foreground)',
              }}
            />
            <Line
              type="monotone"
              dataKey="value"
              name={selected}
              stroke="var(--primary)"
              strokeWidth={2.5}
              dot={false}
              activeDot={{ r: 4 }}
              isAnimationActive={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <div className="grid grid-cols-3 gap-3">
        <Card className="p-3">
          <div className="text-[11px] text-muted-foreground">Финал</div>
          <div className="mt-1 font-mono text-sm">
            {final === undefined ? '—' : formatNumber(final)}
          </div>
        </Card>
        <Card className="p-3">
          <div className="text-[11px] text-muted-foreground">Минимум</div>
          <div className="mt-1 font-mono text-sm">{formatNumber(minimum)}</div>
        </Card>
        <Card className="p-3">
          <div className="text-[11px] text-muted-foreground">Максимум</div>
          <div className="mt-1 font-mono text-sm">{formatNumber(maximum)}</div>
        </Card>
      </div>
      {result.warnings.length > 0 && (
        <Card className="p-4 text-xs leading-5 text-muted-foreground">
          {result.warnings.map((warning) => (
            <p key={warning}>• {warning}</p>
          ))}
        </Card>
      )}
    </div>
  )
}
