import { useMutation, useQuery } from "@tanstack/react-query";
import { runSimulation, getSimulation } from "@/entities/simulation/api";
import { runGuestSimulation } from "@/entities/guest/api";
import { useSimulationStore } from "./model";
import type {
  SimulationParams,
  SimulationResult,
} from "@/entities/simulation/model";
import type { GuestSimulationRequest } from "@/entities/guest/model";

const SIMULATION_KEYS = {
  all: ["simulation"] as const,
  detail: (id: string) => [...SIMULATION_KEYS.all, id] as const,
};

export function useRunSimulation() {
  const { setCurrentResult, setIsRunning, setError } = useSimulationStore();

  return useMutation({
    mutationFn: async (params: SimulationParams) => {
      setIsRunning(true);
      setError(null);
      return runSimulation(params);
    },
    onSuccess: (result: SimulationResult) => {
      setCurrentResult(result);
    },
    onError: (error: Error) => {
      setError(error.message || "Ошибка запуска симуляции");
    },
    onSettled: () => {
      setIsRunning(false);
    },
  });
}

export function useGetSimulation(id: string | null) {
  return useQuery({
    queryKey: SIMULATION_KEYS.detail(id || ""),
    queryFn: () => {
      if (!id) return Promise.resolve(null as SimulationResult | null);
      return getSimulation(id);
    },
    enabled: !!id,
    refetchInterval: (query) => {
      const data = query.state.data;
      if (data?.status === "running" || data?.status === "pending") {
        return 2000;
      }
      return false;
    },
  });
}

export function useRunGuestSimulation() {
  const { setCurrentResult, setIsRunning, setError } = useSimulationStore();

  return useMutation({
    mutationFn: async (params: GuestSimulationRequest) => {
      setIsRunning(true);
      setError(null);
      return runGuestSimulation(params);
    },
    onSuccess: (response) => {
      if (response.status === "error" || response.error) {
        setError(response.error || "Ошибка симуляции");
        setCurrentResult(null);
        return;
      }

      const syntheticResult: SimulationResult = {
        id: `guest-sim-${Date.now()}`,
        model_id: "guest-model",
        status: "completed",
        params: {
          model_id: "guest-model",
          initial_time: response.results?.time[0] ?? 0,
          final_time:
            response.results?.time[response.results.time.length - 1] ?? 0,
          time_step: 0,
          integration_method: "rk4",
        },
        time_series: response.results ?? { time: [], variables: {} },
        created_at: new Date().toISOString(),
        completed_at: new Date().toISOString(),
      };

      setCurrentResult(syntheticResult);
    },
    onError: (error: Error) => {
      setError(error.message || "Ошибка запуска симуляции");
      setCurrentResult(null);
    },
    onSettled: () => {
      setIsRunning(false);
    },
  });
}

