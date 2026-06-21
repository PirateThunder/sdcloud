export type VariableType = "stock" | "flow" | "auxiliary";
export type ModelStatus = "pending" | "generating" | "completed" | "error";

export interface ModelVariable {
  name: string;
  type: VariableType;
  description: string;
  initial_value?: number;
  units?: string;
}

export interface ModelEquation {
  lhs: string;
  rhs: string;
  description?: string;
}

export interface CLDNode {
  id: string;
  label: string;
  type: string;
}

export interface CLDEdge {
  source: string;
  target: string;
  polarity: "+" | "-";
  label?: string;
}

export interface SFDNode {
  id: string;
  label: string;
  type: string;
}

export interface SFDEdge {
  source: string;
  target: string;
  type?: string;
}

export interface CLDData {
  nodes: CLDNode[];
  edges: CLDEdge[];
}

export interface SFDData {
  nodes: SFDNode[];
  edges: SFDEdge[];
}

export interface GeneratedModel {
  id: string;
  name: string;
  description?: string;
  variables: ModelVariable[];
  equations: ModelEquation[];
  cld_data: CLDData;
  sfd_data: SFDData;
  python_code?: string;
  vensim_code?: string;
  status: ModelStatus;
  created_at: string;
  updated_at: string;
  conversation_id?: string;
}

export interface GeneratedModelState {
  currentModel: GeneratedModel | null;
  isLoading: boolean;
  error: string | null;
}
