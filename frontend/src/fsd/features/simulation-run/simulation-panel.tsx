'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertCircle, Play, RotateCcw } from 'lucide-react'
import { type FormEvent, useEffect, useState } from 'react'

import { expressionToString } from '@/fsd/entities/model/lib/expressions'
import type { ModelVersionDetail } from '@/fsd/entities/model/model/types'
import {
  createSimulation,
  listSimulations,
  retrySimulation,
} from '@/fsd/entities/simulation/api/simulation-api'
import type { SimulationParameters } from '@/fsd/entities/simulation/model/types'
import { formatDate } from '@/fsd/shared/lib/utils'
import { Badge } from '@/fsd/shared/ui/badge'
import { Button } from '@/fsd/shared/ui/button'
import { Card } from '@/fsd/shared/ui/card'
import { Input } from '@/fsd/shared/ui/input'
import { Select } from '@/fsd/shared/ui/select'
import { Spinner } from '@/fsd/shared/ui/spinner'

import { SimulationChart } from './simulation-chart'
import { useSimulation } from './use-simulation'

function NumberField({
  id,
  label,
  value,
  onChange,
  step = 'any',
}: {
  id: string
  label: string
  value: string
  onChange: (value: string) => void
  step?: string
}) {
  return (
    <div>
      <label htmlFor={id} className="mb-1.5 block text-xs font-medium text-muted-foreground">
        {label}
      </label>
      <Input
        id={id}
        type="number"
        step={step}
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
    </div>
  )
}

export function SimulationPanel({ version }: { version: ModelVersionDetail }) {
  const queryClient = useQueryClient()
  const time = version.document.time
  const [initialTime, setInitialTime] = useState(String(time.initial_time))
  const [finalTime, setFinalTime] = useState(String(time.final_time))
  const [timeStep, setTimeStep] = useState(String(time.time_step))
  const [saveper, setSaveper] = useState(String(time.saveper))
  const [engine, setEngine] = useState<'auto' | 'pysd' | 'scipy'>('auto')
  const [method, setMethod] = useState<SimulationParameters['integration_method']>('euler')
  const [parameters, setParameters] = useState<Record<string, string>>({})
  const [stockInitial, setStockInitial] = useState<Record<string, string>>({})
  const [selectedId, setSelectedId] = useState<string>()
  const [formError, setFormError] = useState('')
  const selected = useSimulation(selectedId, version.id)
  const history = useQuery({
    queryKey: ['simulations', version.id],
    queryFn: () => listSimulations(version.id),
  })

  useEffect(() => {
    if (!version.id) return
    setSelectedId(undefined)
    setInitialTime(String(time.initial_time))
    setFinalTime(String(time.final_time))
    setTimeStep(String(time.time_step))
    setSaveper(String(time.saveper))
    setParameters({})
    setStockInitial({})
  }, [version.id, time.initial_time, time.final_time, time.time_step, time.saveper])
  useEffect(() => {
    if (!selectedId && history.data?.length) setSelectedId(history.data[0].id)
  }, [history.data, selectedId])

  const create = useMutation({
    mutationFn: (payload: SimulationParameters) =>
      createSimulation(version.id, payload, crypto.randomUUID()),
    onSuccess: (simulation) => {
      setSelectedId(simulation.id)
      void queryClient.invalidateQueries({ queryKey: ['simulations', version.id] })
    },
  })
  const retry = useMutation({
    mutationFn: (id: string) => retrySimulation(id),
    onSuccess: (simulation) => {
      setSelectedId(simulation.id)
      void queryClient.invalidateQueries({ queryKey: ['simulations', version.id] })
    },
  })

  const submit = (event: FormEvent) => {
    event.preventDefault()
    setFormError('')
    const initial = Number(initialTime)
    const final = Number(finalTime)
    const step = Number(timeStep)
    const save = Number(saveper)
    if (
      ![initial, final, step, save].every(Number.isFinite) ||
      final <= initial ||
      step <= 0 ||
      save <= 0
    ) {
      setFormError('Проверьте горизонт и шаги: final > initial, time step и saveper > 0.')
      return
    }
    const constants = Object.fromEntries(
      Object.entries(parameters)
        .filter(([, value]) => value.trim())
        .map(([name, value]) => [name, Number(value)]),
    )
    const stocks = Object.fromEntries(
      Object.entries(stockInitial)
        .filter(([, value]) => value.trim())
        .map(([name, value]) => [name, Number(value)]),
    )
    if (
      [...Object.values(constants), ...Object.values(stocks)].some(
        (value) => !Number.isFinite(value),
      )
    ) {
      setFormError('Параметры и начальные значения должны быть конечными числами.')
      return
    }
    create.mutate({
      engine,
      integration_method: method,
      initial_time: initial,
      final_time: final,
      time_step: step,
      saveper: save,
      parameters: constants,
      stock_initial: stocks,
    })
  }

  const scalarVariables = version.document.variables.filter(
    (variable) => !variable.subscripts?.length,
  )
  const constants = scalarVariables.filter((variable) => variable.kind === 'constant')
  const stocks = scalarVariables.filter((variable) => variable.kind === 'stock')
  const result = selected.data?.result

  return (
    <div className="grid items-start gap-5 xl:grid-cols-[340px_minmax(0,1fr)]">
      <Card className="p-4">
        <div className="mb-4">
          <h2 className="font-semibold">Новый эксперимент</h2>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">
            Запуск привязан к версии {version.version} и её model hash.
          </p>
        </div>
        <form onSubmit={submit} className="space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <NumberField
              id="sim-initial"
              label="Начальное время"
              value={initialTime}
              onChange={setInitialTime}
            />
            <NumberField
              id="sim-final"
              label="Конечное время"
              value={finalTime}
              onChange={setFinalTime}
            />
            <NumberField id="sim-step" label="Time step" value={timeStep} onChange={setTimeStep} />
            <NumberField id="sim-saveper" label="Saveper" value={saveper} onChange={setSaveper} />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label
                htmlFor="sim-engine"
                className="mb-1.5 block text-xs font-medium text-muted-foreground"
              >
                Engine
              </label>
              <Select
                id="sim-engine"
                className="w-full"
                value={engine}
                onChange={(event) => setEngine(event.target.value as typeof engine)}
              >
                <option value="auto">Auto</option>
                <option value="pysd">PySD</option>
                <option value="scipy">SciPy</option>
              </Select>
            </div>
            <div>
              <label
                htmlFor="sim-method"
                className="mb-1.5 block text-xs font-medium text-muted-foreground"
              >
                Метод
              </label>
              <Select
                id="sim-method"
                className="w-full"
                value={method}
                onChange={(event) => setMethod(event.target.value as typeof method)}
              >
                {['euler', 'rk4', 'rk45', 'dop853', 'lsoda', 'bdf'].map((item) => (
                  <option key={item} value={item}>
                    {item}
                  </option>
                ))}
              </Select>
            </div>
          </div>
          {constants.length > 0 && (
            <details className="rounded-lg border border-border p-3">
              <summary className="text-xs font-medium">
                Параметры constants ({constants.length})
              </summary>
              <div className="mt-3 space-y-3">
                {constants.map((variable) => (
                  <NumberField
                    key={variable.id}
                    id={`param-${variable.id}`}
                    label={variable.id}
                    value={parameters[variable.id] ?? ''}
                    onChange={(value) => setParameters((old) => ({ ...old, [variable.id]: value }))}
                  />
                ))}
                <p className="text-[11px] leading-4 text-muted-foreground">
                  Пустое поле сохраняет значение из модели:{' '}
                  {constants
                    .map((item) => `${item.id}=${expressionToString(item.expression)}`)
                    .join(', ')}
                </p>
              </div>
            </details>
          )}
          {stocks.length > 0 && (
            <details className="rounded-lg border border-border p-3">
              <summary className="text-xs font-medium">Начальные stocks ({stocks.length})</summary>
              <div className="mt-3 space-y-3">
                {stocks.map((variable) => (
                  <NumberField
                    key={variable.id}
                    id={`stock-${variable.id}`}
                    label={`${variable.id} · ${expressionToString(variable.initial)}`}
                    value={stockInitial[variable.id] ?? ''}
                    onChange={(value) =>
                      setStockInitial((old) => ({ ...old, [variable.id]: value }))
                    }
                  />
                ))}
              </div>
            </details>
          )}
          {formError && (
            <p role="alert" className="text-xs text-destructive">
              {formError}
            </p>
          )}
          {create.isError && (
            <p role="alert" className="text-xs text-destructive">
              {create.error.message}
            </p>
          )}
          <Button type="submit" className="w-full" disabled={create.isPending}>
            <Play /> {create.isPending ? 'Запускаем…' : 'Запустить симуляцию'}
          </Button>
        </form>
      </Card>
      <div className="min-w-0 space-y-5">
        {!selectedId ? (
          <Card className="grid min-h-64 place-items-center p-8 text-center text-sm text-muted-foreground">
            Настройте параметры и запустите первую симуляцию этой версии.
          </Card>
        ) : selected.isPending ? (
          <div className="grid min-h-64 place-items-center">
            <Spinner />
          </div>
        ) : selected.data?.status === 'error' ? (
          <Card className="border-destructive/30 p-5">
            <div className="flex gap-3">
              <AlertCircle className="size-5 text-destructive" />
              <div>
                <h3 className="font-medium">Симуляция завершилась ошибкой</h3>
                <p className="mt-2 text-sm text-muted-foreground">{selected.data.error}</p>
                <Button
                  size="sm"
                  variant="outline"
                  className="mt-4"
                  onClick={() => {
                    if (selected.data) retry.mutate(selected.data.id)
                  }}
                  disabled={retry.isPending}
                >
                  <RotateCcw /> Повторить
                </Button>
              </div>
            </div>
          </Card>
        ) : result ? (
          <SimulationChart result={result} />
        ) : (
          <Card className="flex min-h-64 items-center justify-center gap-3 p-6 text-sm text-muted-foreground">
            <Spinner /> Выполняется {selected.data?.stage ?? selected.data?.status ?? 'simulation'}…
          </Card>
        )}
        {history.data && history.data.length > 0 && (
          <Card className="overflow-hidden">
            <div className="border-b border-border px-4 py-3 text-sm font-medium">
              История запусков
            </div>
            <div className="max-h-64 overflow-y-auto">
              {history.data.map((simulation) => (
                <button
                  key={simulation.id}
                  type="button"
                  onClick={() => setSelectedId(simulation.id)}
                  className="flex w-full items-center justify-between gap-3 border-b border-border px-4 py-3 text-left text-xs last:border-0 hover:bg-muted"
                >
                  <span>
                    <span className="font-mono">#{simulation.attempt}</span> ·{' '}
                    {formatDate(simulation.created_at)}
                  </span>
                  <Badge
                    className={
                      simulation.status === 'error'
                        ? 'bg-destructive/10 text-destructive'
                        : simulation.status === 'done'
                          ? 'bg-accent text-accent-foreground'
                          : ''
                    }
                  >
                    {simulation.status}
                  </Badge>
                </button>
              ))}
            </div>
          </Card>
        )}
      </div>
    </div>
  )
}
