import { create } from "zustand";
import type { SimulationResult, SimulationParams } from "@/entities/simulation/model";

interface SimulationState {
  currentResult: SimulationResult | null;
  isRunning: boolean;
  error: string | null;
  params: SimulationParams | null;

  setCurrentResult: (result: SimulationResult | null) => void;
  setIsRunning: (running: boolean) => void;
  setError: (error: string | null) => void;
  setParams: (params: SimulationParams | null) => void;
  clearSimulation: () => void;
}

export const useSimulationStore = create<SimulationState>((set) => ({
  currentResult: null,
  isRunning: false,
  error: null,
  params: null,

  setCurrentResult: (currentResult) => set({ currentResult }),
  setIsRunning: (isRunning) => set({ isRunning }),
  setError: (error) => set({ error }),
  setParams: (params) => set({ params }),
  clearSimulation: () =>
    set({ currentResult: null, isRunning: false, error: null, params: null }),
}));
