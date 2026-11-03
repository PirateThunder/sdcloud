'use client'

import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, MessageSquare } from 'lucide-react'
import Link from 'next/link'
import { useEffect, useState } from 'react'

import { getModel, getModelVersion, listModelVersions } from '@/fsd/entities/model/api/model-api'
import {
  CodeView,
  EquationsView,
  ModelOverview,
  VariablesView,
} from '@/fsd/entities/model/ui/model-details'
import { ModelGraphView } from '@/fsd/entities/model/ui/model-graph'
import { SimulationPanel } from '@/fsd/features/simulation-run/simulation-panel'
import { cn, formatDate } from '@/fsd/shared/lib/utils'
import { Badge } from '@/fsd/shared/ui/badge'
import { Button } from '@/fsd/shared/ui/button'
import { Card } from '@/fsd/shared/ui/card'
import { Select } from '@/fsd/shared/ui/select'
import { Spinner } from '@/fsd/shared/ui/spinner'

const tabs = [
  ['overview', 'Обзор'],
  ['cld', 'CLD'],
  ['sfd', 'SFD'],
  ['equations', 'Уравнения'],
  ['variables', 'Переменные'],
  ['code', 'Код'],
  ['simulation', 'Симуляция'],
] as const
type Tab = (typeof tabs)[number][0]

export function ModelWorkspacePage({
  modelId,
  versionId,
}: {
  modelId?: string
  versionId?: string
}) {
  const directVersion = useQuery({
    queryKey: ['model-version', versionId],
    queryFn: () => getModelVersion(versionId as string),
    enabled: Boolean(versionId),
  })
  const resolvedModelId = modelId ?? directVersion.data?.model_id
  const model = useQuery({
    queryKey: ['model', resolvedModelId],
    queryFn: () => getModel(resolvedModelId as string),
    enabled: Boolean(resolvedModelId),
  })
  const versions = useQuery({
    queryKey: ['model-versions', resolvedModelId],
    queryFn: () => listModelVersions(resolvedModelId as string),
    enabled: Boolean(resolvedModelId),
  })
  const [selectedId, setSelectedId] = useState(versionId)
  useEffect(() => {
    if (!selectedId && model.data) setSelectedId(model.data.latest_version_id)
  }, [model.data, selectedId])
  const version = useQuery({
    queryKey: ['model-version', selectedId],
    queryFn: () => getModelVersion(selectedId as string),
    enabled: Boolean(selectedId),
  })
  const [tab, setTab] = useState<Tab>('overview')

  if ((versionId && directVersion.isPending) || model.isPending || version.isPending) {
    return (
      <div className="grid min-h-64 place-items-center">
        <Spinner />
      </div>
    )
  }
  if (directVersion.isError || model.isError || version.isError || !model.data || !version.data) {
    return (
      <Card className="m-6 p-6 text-sm text-destructive">Модель не найдена или недоступна</Card>
    )
  }

  const document = version.data.document
  return (
    <div className="mx-auto max-w-7xl p-4 sm:p-6 lg:p-8">
      <div className="mb-6">
        <Button render={<Link href="/models" />} variant="ghost" size="sm" className="-ml-2 mb-4">
          <ArrowLeft /> Библиотека
        </Button>
        <div className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
          <div className="min-w-0">
            <div className="mb-2 flex flex-wrap items-center gap-2">
              <Badge className="bg-accent text-accent-foreground">System Dynamics</Badge>
              <Badge>Schema {document.schema_version}</Badge>
              <span className="text-xs text-muted-foreground">v{version.data.version}</span>
            </div>
            <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">{model.data.name}</h1>
            <p className="mt-2 text-sm text-muted-foreground">
              {document.variables.length} переменных · {formatDate(version.data.created_at)}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Select
              aria-label="Версия модели"
              value={selectedId}
              onChange={(event) => setSelectedId(event.target.value)}
              className="max-w-full"
            >
              {versions.data?.map((item) => (
                <option key={item.id} value={item.id}>
                  Версия {item.version} · {formatDate(item.created_at)}
                </option>
              ))}
            </Select>
            <Button
              render={<Link href={`/chat/${model.data.conversation_id}`} />}
              variant="outline"
            >
              <MessageSquare /> Открыть чат
            </Button>
          </div>
        </div>
      </div>
      <div
        role="tablist"
        aria-label="Разделы модели"
        className="mb-5 flex gap-1 overflow-x-auto rounded-xl border border-border bg-card p-1"
      >
        {tabs.map(([value, label]) => (
          <button
            key={value}
            type="button"
            role="tab"
            aria-selected={tab === value}
            onClick={() => setTab(value)}
            className={cn(
              'rounded-lg px-3 py-2 text-xs font-medium whitespace-nowrap text-muted-foreground transition-colors hover:bg-muted hover:text-foreground',
              tab === value && 'bg-secondary text-foreground',
            )}
          >
            {label}
          </button>
        ))}
      </div>
      <div role="tabpanel">
        {tab === 'overview' && <ModelOverview version={version.data} />}
        {tab === 'cld' &&
          (document.cld_data ? (
            <ModelGraphView graph={document.cld_data} mode="cld" />
          ) : (
            <Card className="p-6 text-sm text-muted-foreground">
              CLD недоступна для этой версии
            </Card>
          ))}
        {tab === 'sfd' &&
          (document.sfd_data ? (
            <ModelGraphView graph={document.sfd_data} mode="sfd" />
          ) : (
            <Card className="p-6 text-sm text-muted-foreground">
              SFD недоступна для этой версии
            </Card>
          ))}
        {tab === 'equations' && <EquationsView version={version.data} />}
        {tab === 'variables' && <VariablesView version={version.data} />}
        {tab === 'code' && <CodeView version={version.data} />}
        {tab === 'simulation' && <SimulationPanel version={version.data} />}
      </div>
    </div>
  )
}
