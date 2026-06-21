export interface SimulationParams {
  model_id: string;
  initial_time: number;
  final_time: number;
  time_step: number;
  integration_method: "euler" | "rk4";
  parameter_overrides?: Record<string, number>;
}

export interface SimulationResult {
  id: string;
  model_id: string;
  status: "pending" | "running" | "completed" | "error";
  params: SimulationParams;
  time_series: TimeSeriesData;
  error_message?: string;
  created_at: string;
  completed_at?: string;
}

export interface TimeSeriesData {
  time: number[];
  variables: Record<string, number[]>;
}

export interface SimulationState {
  currentSimulation: SimulationResult | null;
  isRunning: boolean;
  error: string | null;
}
