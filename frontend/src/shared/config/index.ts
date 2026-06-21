export const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export const API_ROUTES = {
  auth: {
    login: `${API_BASE_URL}/api/v1/auth/login`,
    register: `${API_BASE_URL}/api/v1/auth/register`,
    me: `${API_BASE_URL}/api/v1/auth/me`,
  },
  conversations: {
    list: `${API_BASE_URL}/api/v1/conversations`,
    detail: (id: string) => `${API_BASE_URL}/api/v1/conversations/${id}`,
    messages: (id: string) => `${API_BASE_URL}/api/v1/conversations/${id}/messages`,
    send: (id: string) => `${API_BASE_URL}/api/v1/conversations/${id}/send`,
  },
  models: {
    list: `${API_BASE_URL}/api/v1/models`,
    detail: (id: string) => `${API_BASE_URL}/api/v1/models/${id}`,
  },
  simulation: {
    run: `${API_BASE_URL}/api/v1/simulation/run`,
    result: (id: string) => `${API_BASE_URL}/api/v1/simulation/${id}`,
  },
} as const;

export const APP_ROUTES = {
  home: "/",
  chat: "/chat",
  login: "/login",
  register: "/register",
} as const;

export const STORAGE_KEYS = {
  accessToken: "access_token",
  refreshToken: "refresh_token",
} as const;
