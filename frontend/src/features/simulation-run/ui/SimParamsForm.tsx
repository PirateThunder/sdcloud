"use client";

import React, { useState } from "react";
import { Button } from "@/shared/ui/button";
import { Input } from "@/shared/ui/input";
import { Label } from "@/shared/ui/label";
import { Card, CardContent, CardHeader, CardTitle } from "@/shared/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/shared/ui/select";
import {
  useRunSimulation,
  useRunGuestSimulation,
} from "../api";
import { useSimulationStore } from "../model";
import { useAuthStore } from "@/features/auth/model";
import type { GeneratedModel } from "@/entities/model/model";
import { Play, Loader2, Settings2 } from "lucide-react";

interface SimParamsFormProps {
  model: GeneratedModel;
}

export function SimParamsForm({ model }: SimParamsFormProps) {
  const [initialTime, setInitialTime] = useState(0);
  const [finalTime, setFinalTime] = useState(100);
  const [timeStep, setTimeStep] = useState(0.1);
  const [integrationMethod, setIntegrationMethod] = useState<"euler" | "rk4">(
    "rk4"
  );
  const [paramOverrides, setParamOverrides] = useState<
    Record<string, number>
  >({});

  const { isAuthenticated } = useAuthStore();
  const runSim = useRunSimulation();
  const runGuestSim = useRunGuestSimulation();
  const { isRunning } = useSimulationStore();

  const handleRun = () => {
    if (!isAuthenticated) {
      runGuestSim.mutate({
        python_code: model.python_code || undefined,
        vensim_code: model.vensim_code || undefined,
        parameters: {
          time_start: initialTime,
          time_end: finalTime,
          time_step: timeStep,
          custom_params: paramOverrides,
        },
      });
      return;
    }

    runSim.mutate({
      model_id: model.id,
      initial_time: initialTime,
      final_time: finalTime,
      time_step: timeStep,
      integration_method: integrationMethod,
      parameter_overrides:
        Object.keys(paramOverrides).length > 0 ? paramOverrides : undefined,
    });
  };

  const stockVariables = model.variables?.filter((v) => v.type === "stock") || [];

  return (
    <Card className="border-border/50">
      <CardHeader className="pb-3">
        <CardTitle className="text-sm font-medium flex items-center gap-2">
          <Settings2 className="h-4 w-4 text-muted-foreground" />
          Параметры симуляции
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid grid-cols-3 gap-3">
          <div className="space-y-1.5">
            <Label htmlFor="initialTime" className="text-xs">
              Начальное время
            </Label>
            <Input
              id="initialTime"
              type="number"
              value={initialTime}
              onChange={(e) => setInitialTime(Number(e.target.value))}
              className="h-8 text-sm"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="finalTime" className="text-xs">
              Конечное время
            </Label>
            <Input
              id="finalTime"
              type="number"
              value={finalTime}
              onChange={(e) => setFinalTime(Number(e.target.value))}
              className="h-8 text-sm"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="timeStep" className="text-xs">
              Шаг времени
            </Label>
            <Input
              id="timeStep"
              type="number"
              value={timeStep}
              onChange={(e) => setTimeStep(Number(e.target.value))}
              step={0.01}
              min={0.001}
              className="h-8 text-sm"
            />
          </div>
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="integrationMethod" className="text-xs">
            Метод интеграции
          </Label>
          <Select
            value={integrationMethod}
            onValueChange={(v: "euler" | "rk4") => setIntegrationMethod(v)}
          >
            <SelectTrigger className="h-8 text-sm">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="euler">Эйлер (Euler)</SelectItem>
              <SelectItem value="rk4">
                Рунге-Кутта 4-го порядка (RK4)
              </SelectItem>
            </SelectContent>
          </Select>
        </div>

        {stockVariables.length > 0 && (
          <div className="space-y-2">
            <Label className="text-xs">Начальные значения (Stocks)</Label>
            <div className="grid grid-cols-2 gap-2">
              {stockVariables.map((variable) => (
                <div key={variable.name} className="space-y-1">
                  <Label className="text-[10px] text-muted-foreground">
                    {variable.name}
                    {variable.units ? ` (${variable.units})` : ""}
                  </Label>
                  <Input
                    type="number"
                    defaultValue={variable.initial_value ?? 0}
                    onChange={(e) =>
                      setParamOverrides((prev) => ({
                        ...prev,
                        [variable.name]: Number(e.target.value),
                      }))
                    }
                    className="h-7 text-xs"
                  />
                </div>
              ))}
            </div>
          </div>
        )}

        <Button
          onClick={handleRun}
          disabled={isRunning}
          className="w-full"
          size="sm"
        >
          {isRunning ? (
            <>
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              Запуск симуляции...
            </>
          ) : (
            <>
              <Play className="mr-2 h-4 w-4" />
              Запустить симуляцию
            </>
          )}
        </Button>
      </CardContent>
    </Card>
  );
}
