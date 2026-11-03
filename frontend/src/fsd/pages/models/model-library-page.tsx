'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowUpRight, Box, Plus, Trash2 } from 'lucide-react'
import Link from 'next/link'
import { useState } from 'react'

import { deleteModel, listModels } from '@/fsd/entities/model/api/model-api'
import { formatDate } from '@/fsd/shared/lib/utils'
import { Badge } from '@/fsd/shared/ui/badge'
import { Button } from '@/fsd/shared/ui/button'
import { Card } from '@/fsd/shared/ui/card'
import { EmptyState } from '@/fsd/shared/ui/empty-state'
import { Spinner } from '@/fsd/shared/ui/spinner'

export function ModelLibraryPage() {
  const queryClient = useQueryClient()
  const models = useQuery({ queryKey: ['models'], queryFn: listModels })
  const [confirmId, setConfirmId] = useState<string | null>(null)
  const remove = useMutation({
    mutationFn: deleteModel,
    onSuccess: async () => {
      setConfirmId(null)
      await queryClient.invalidateQueries({ queryKey: ['models'] })
    },
  })

  return (
    <div className="mx-auto max-w-6xl p-4 sm:p-8">
      <div className="mb-7 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Библиотека моделей</h1>
          <p className="mt-2 text-sm text-muted-foreground">
            Версии, диаграммы и эксперименты вашего рабочего пространства.
          </p>
        </div>
        <Button render={<Link href="/chat" />}>
          <Plus /> Новая модель
        </Button>
      </div>
      {models.isPending ? (
        <div className="grid min-h-64 place-items-center">
          <Spinner />
        </div>
      ) : models.isError ? (
        <Card className="p-6 text-sm text-destructive">Не удалось загрузить библиотеку</Card>
      ) : models.data?.length === 0 ? (
        <EmptyState
          icon={Box}
          title="Пока нет моделей"
          description="Создайте первую модель в чате — после генерации здесь появятся её версии, диаграммы и симуляции."
        />
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {models.data?.map((model) => (
            <Card key={model.id} className="flex min-h-56 flex-col p-5">
              <div className="flex items-start justify-between gap-3">
                <div className="grid size-10 place-items-center rounded-xl bg-accent text-accent-foreground">
                  <Box className="size-5" />
                </div>
                <Badge>v{model.latest_version}</Badge>
              </div>
              <h2 className="mt-4 line-clamp-2 font-semibold">{model.name}</h2>
              <p className="mt-2 text-xs text-muted-foreground">
                Обновлена {formatDate(model.updated_at)}
              </p>
              <div className="mt-auto flex items-end justify-between gap-2 pt-5">
                <Button render={<Link href={`/models/${model.id}`} />} size="sm" variant="outline">
                  Открыть <ArrowUpRight />
                </Button>
                {confirmId === model.id ? (
                  <div className="flex gap-1">
                    <Button
                      size="sm"
                      variant="destructive"
                      onClick={() => remove.mutate(model.id)}
                      disabled={remove.isPending}
                    >
                      Да
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => setConfirmId(null)}>
                      Нет
                    </Button>
                  </div>
                ) : (
                  <Button
                    size="icon-sm"
                    variant="ghost"
                    onClick={() => setConfirmId(model.id)}
                    aria-label={`Удалить ${model.name}`}
                  >
                    <Trash2 />
                  </Button>
                )}
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}
