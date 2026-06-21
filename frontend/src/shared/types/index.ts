export interface ApiResponse<T> {
  data: T;
  message?: string;
  success: boolean;
}

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export interface ApiError {
  detail: string | Array<{ loc: string[]; msg: string; type: string }>;
  status?: number;
}

export type LoadingState = "idle" | "loading" | "success" | "error";

export interface SelectOption {
  label: string;
  value: string;
}
