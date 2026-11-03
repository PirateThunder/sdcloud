'use client'

import { useQuery } from '@tanstack/react-query'
import { Download, FileCode2 } from 'lucide-react'
import { useState } from 'react'

import { downloadAuthedFile } from '@/fsd/shared/api/http'
import { formatDate, formatNumber } from '@/fsd/shared/lib/utils'
import { Badge } from '@/fsd/shared/ui/badge'
import { Button } from '@/fsd/shared/ui/button'
import { Card } from '@/fsd/shared/ui/card'
import { MathFormula } from '@/fsd/shared/ui/math-formula'
import { Select } from '@/fsd/shared/ui/select'
import { Spinner } from '@/fsd/shared/ui/spinner'

import { exportPath, getExportText } from '../api/model-api'
import {
  expressionToLatex,
  stockInitialLatex,
  unitsToLatex,
  variableEquationLatex,
} from '../lib/latex'
import type { ExportFormat, ModelVersionDetail } from '../model/types'

const kindNames = { stock: 'Stock', flow: 'Flow', auxiliary: 'Auxiliary', constant: 'Constant' }
const exportNames: Record<ExportFormat, string> = {
  python: 'Python',
  vensim: 'Vensim',
  xmile: 'XMILE',
}

export function ModelOverview({ version }: { version: ModelVersionDetail }) {
  const { document } = version
  const counts = Object.groupBy(document.variables, (variable) => variable.kind)
  const issues = document.validation?.issues ?? []
  return (
    <div className="space-y-4">
      <Card className="p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold">{document.name}</h2>
            <p className="mt-2 max-w-3xl text-sm leading-6 text-muted-foreground">
              {document.description}
            </p>
          </div>
          <Badge className="bg-accent text-accent-foreground">
            {document.validation?.status ?? 'validated'}
          </Badge>
        </div>
      </Card>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {Object.entries(counts).map(([kind, variables]) => (
          <Card key={kind} className="p-4">
            <div className="text-xs text-muted-foreground">
              {kindNames[kind as keyof typeof kindNames]}
            </div>
            <div className="mt-1 text-2xl font-semibold">{variables?.length ?? 0}</div>
          </Card>
        ))}
        <Card className="p-4">
          <div className="text-xs text-muted-foreground">Горизонт</div>
          <div className="mt-1 text-lg font-semibold">
            {formatNumber(document.time.initial_time)}–{formatNumber(document.time.final_time)}
          </div>
          <div className="text-xs text-muted-foreground">{document.time.unit}</div>
        </Card>
      </div>
      <Card className="grid gap-4 p-5 text-sm sm:grid-cols-3">
        <div>
          <div className="text-xs text-muted-foreground">Шаг интегрирования</div>
          <div className="mt-1 font-mono">{document.time.time_step}</div>
        </div>
        <div>
          <div className="text-xs text-muted-foreground">Шаг сохранения</div>
          <div className="mt-1 font-mono">{document.time.saveper}</div>
        </div>
        <div>
          <div className="text-xs text-muted-foreground">Версия создана</div>
          <div className="mt-1">{formatDate(version.created_at)}</div>
        </div>
      </Card>
      {issues.length > 0 && (
        <Card className="p-5">
          <h3 className="mb-3 font-medium">Проверки и предупреждения</h3>
          <ul className="space-y-2 text-sm text-muted-foreground">
            {issues.map((issue) => (
              <li key={JSON.stringify(issue)}>
                {typeof issue === 'object' && issue && 'message' in issue
                  ? String(issue.message)
                  : JSON.stringify(issue)}
              </li>
            ))}
          </ul>
        </Card>
      )}
      {(document.assumptions?.length ?? 0) > 0 && (
        <Card className="p-5">
          <h3 className="mb-3 font-medium">Допущения модели</h3>
          <ul className="space-y-2 text-sm leading-6 text-muted-foreground">
            {document.assumptions?.map((assumption) => (
              <li key={JSON.stringify(assumption)}>
                • {assumption.rationale ?? 'Требуется проверка допущения'}
              </li>
            ))}
          </ul>
        </Card>
      )}
      <div className="text-xs text-muted-foreground">
        SHA-256: <span className="break-all font-mono">{version.model_hash}</span>
      </div>
    </div>
  )
}

export function VariablesView({ version }: { version: ModelVersionDetail }) {
  return (
    <Card className="overflow-x-auto">
      <table className="w-full min-w-[760px] border-collapse text-sm">
        <thead className="bg-muted text-left text-xs text-muted-foreground">
          <tr>
            <th className="px-4 py-3 font-medium">Переменная</th>
            <th className="px-4 py-3 font-medium">Тип</th>
            <th className="px-4 py-3 font-medium">Единицы</th>
            <th className="px-4 py-3 font-medium">Начальное значение / выражение</th>
          </tr>
        </thead>
        <tbody>
          {version.document.variables.map((variable) => (
            <tr key={variable.id} className="border-t border-border align-top">
              <td className="px-4 py-3">
                <div className="font-mono text-xs font-medium">{variable.id}</div>
                {variable.label && variable.label !== variable.id && (
                  <div className="mt-1 text-xs text-muted-foreground">{variable.label}</div>
                )}
              </td>
              <td className="px-4 py-3">
                <Badge>{kindNames[variable.kind]}</Badge>
              </td>
              <td className="px-4 py-3 text-xs">
                <MathFormula formula={unitsToLatex(variable.units)} display={false} />
              </td>
              <td className="max-w-md px-4 py-3 text-xs leading-5 break-words">
                <MathFormula
                  formula={expressionToLatex(
                    variable.kind === 'stock' ? variable.initial : variable.expression,
                  )}
                  display={false}
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  )
}

export function EquationsView({ version }: { version: ModelVersionDetail }) {
  return (
    <div className="space-y-3">
      {version.document.variables.map((variable) => (
        <Card key={variable.id} className="p-4">
          <div className="mb-2 flex items-center gap-2">
            <Badge>{kindNames[variable.kind]}</Badge>
            <span className="font-mono text-xs text-muted-foreground">{variable.id}</span>
          </div>
          <MathFormula formula={variableEquationLatex(variable, version.document.variables)} />
          {variable.kind === 'stock' && (
            <MathFormula
              formula={stockInitialLatex(variable)}
              display={false}
              className="mt-3 text-muted-foreground"
            />
          )}
        </Card>
      ))}
    </div>
  )
}

export function CodeView({ version }: { version: ModelVersionDetail }) {
  const [format, setFormat] = useState<ExportFormat>('python')
  const code = useQuery({
    queryKey: ['model-export', version.id, format],
    queryFn: () => getExportText(version.model_id, version.version, format),
  })
  const download = () =>
    downloadAuthedFile(
      exportPath(version.model_id, version.version, format),
      `model.${format === 'python' ? 'py' : format === 'vensim' ? 'mdl' : 'xmile'}`,
    )
  return (
    <Card className="overflow-hidden">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border p-3">
        <div className="flex items-center gap-2">
          <FileCode2 className="size-4 text-primary" />
          <Select
            aria-label="Формат кода"
            value={format}
            onChange={(event) => setFormat(event.target.value as ExportFormat)}
          >
            {version.available_exports.map((item) => (
              <option key={item} value={item}>
                {exportNames[item as ExportFormat]}
              </option>
            ))}
          </Select>
        </div>
        <Button size="sm" variant="outline" onClick={() => void download()}>
          <Download /> Скачать {exportNames[format]}
        </Button>
      </div>
      {code.isPending ? (
        <div className="grid h-64 place-items-center">
          <Spinner />
        </div>
      ) : code.isError ? (
        <p className="p-5 text-sm text-destructive">Не удалось загрузить код</p>
      ) : (
        <pre className="max-h-[650px] overflow-auto bg-muted p-5 font-mono text-xs leading-6">
          <code>{code.data}</code>
        </pre>
      )}
    </Card>
  )
}
