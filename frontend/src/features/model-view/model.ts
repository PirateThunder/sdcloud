import { create } from "zustand";
import type { GeneratedModel } from "@/entities/model/model";

type ModelViewTab = "cld" | "sfd" | "equations" | "simulation";

interface ModelViewState {
  activeTab: ModelViewTab;
  selectedModel: GeneratedModel | null;
  setActiveTab: (tab: ModelViewTab) => void;
  setSelectedModel: (model: GeneratedModel | null) => void;
}

export const useModelViewStore = create<ModelViewState>((set) => ({
  activeTab: "cld",
  selectedModel: null,
  setActiveTab: (activeTab) => set({ activeTab }),
  setSelectedModel: (selectedModel) => set({ selectedModel }),
}));
