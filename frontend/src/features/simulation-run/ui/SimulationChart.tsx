"use client";

import React from "react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";
import type { TimeSeriesData } from "@/entities/simulation/model";

interface SimulationChartProps {
  timeSeries: TimeSeriesData;
  height?: number;
}

const COLORS = [
  "#10b981", // emerald
  "#3b82f6", // blue
  "#f59e0b", // amber
  "#ef4444", // red
  "#8b5cf6", // violet
  "#ec4899", // pink
  "#06b6d4", // cyan
  "#84cc16", // lime
  "#f97316", // orange
  "#6366f1", // indigo
];

export function SimulationChart({
  timeSeries,
  height = 400,
}: SimulationChartProps) {
  if (!timeSeries?.time?.length || !timeSeries?.variables) {
    return (
      <div className="flex items-center justify-center h-[300px] text-muted-foreground text-sm border border-border/50 rounded-lg">
        Нет данных для отображения
      </div>
    );
  }

  // Transform data for recharts
  const chartData = timeSeries.time.map((t, index) => {
    const point: Record<string, number> = { time: t };
    Object.entries(timeSeries.variables).forEach(([key, values]) => {
      point[key] = values[index] ?? 0;
    });
    return point;
  });

  const variableNames = Object.keys(timeSeries.variables);

  if (variableNames.length === 0) {
    return (
      <div className="flex items-center justify-center h-[300px] text-muted-foreground text-sm border border-border/50 rounded-lg">
        Нет переменных для отображения
      </div>
    );
  }

  return (
    <div className="border border-border/50 rounded-lg p-4 bg-background">
      <ResponsiveContainer width="100%" height={height}>
        <LineChart
          data={chartData}
          margin={{ top: 5, right: 30, left: 20, bottom: 5 }}
        >
          <CartesianGrid
            strokeDasharray="3 3"
            stroke="hsl(240, 5%, 25%)"
            opacity={0.3}
          />
          <XAxis
            dataKey="time"
            stroke="hsl(240, 5%, 65%)"
            fontSize={12}
            tickLine={false}
            axisLine={false}
            label={{
              value: "Время",
              position: "insideBottomRight",
              offset: -5,
              style: { fill: "hsl(240, 5%, 65%)", fontSize: 12 },
            }}
          />
          <YAxis
            stroke="hsl(240, 5%, 65%)"
            fontSize={12}
            tickLine={false}
            axisLine={false}
            label={{
              value: "Значение",
              angle: -90,
              position: "insideLeft",
              style: { fill: "hsl(240, 5%, 65%)", fontSize: 12 },
            }}
          />
          <Tooltip
            contentStyle={{
              backgroundColor: "hsl(240, 10%, 8%)",
              border: "1px solid hsl(240, 5%, 25%)",
              borderRadius: "8px",
              fontSize: "12px",
            }}
            labelStyle={{ color: "hsl(0, 0%, 98%)", marginBottom: "4px" }}
          />
          <Legend
            wrapperStyle={{ fontSize: "12px", paddingTop: "10px" }}
          />
          {variableNames.map((name, index) => (
            <Line
              key={name}
              type="monotone"
              dataKey={name}
              stroke={COLORS[index % COLORS.length]}
              strokeWidth={2}
              dot={false}
              activeDot={{ r: 4 }}
              name={name}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
