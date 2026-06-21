"use client";

import React from "react";
import { SimParamsForm } from "./SimParamsForm";
import { SimulationChart } from "./SimulationChart";
import { useSimulationStore } from "../model";
import type { GeneratedModel } from "@/entities/model/model";
import { Separator } from "@/shared/ui/separator";
import { AlertCircle } from "lucide-react";

interface SimulationPanelProps {
  model: GeneratedModel;
}

export function SimulationPanel({ model }: SimulationPanelProps) {
  const { currentResult, error } = useSimulationStore();

  return (
    <div className="space-y-4">
      <SimParamsForm model={model} />

      {error && (
        <div className="flex items-center gap-2 p-3 rounded-md bg-destructive/10 text-destructive text-sm">
          <AlertCircle className="h-4 w-4 shrink-0" />
          {error}
        </div>
      )}

      {currentResult && (
        <div className="space-y-3">
          <Separator />
          <div className="flex items-center justify-between">
            <h4 className="text-sm font-medium">Результаты симуляции</h4>
            {currentResult.status === "completed" && (
              <span className="text-xs text-emerald-400 bg-emerald-400/10 px-2 py-0.5 rounded">
                Завершено
              </span>
            )}
            {currentResult.status === "error" && (
              <span className="text-xs text-destructive bg-destructive/10 px-2 py-0.5 rounded">
                Ошибка
              </span>
            )}
            {(currentResult.status === "running" ||
              currentResult.status === "pending") && (
              <span className="text-xs text-blue-400 bg-blue-400/10 px-2 py-0.5 rounded animate-pulse">
                Выполняется...
              </span>
            )}
          </div>
          {currentResult.error_message && (
            <p className="text-xs text-destructive">
              {currentResult.error_message}
            </p>
          )}
          {currentResult.time_series && (
            <SimulationChart
              timeSeries={currentResult.time_series}
              height={400}
            />
          )}
        </div>
      )}
    </div>
  );
}
