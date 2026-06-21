import { create } from "zustand";
import { persist } from "zustand/middleware";
import { STORAGE_KEYS } from "@/shared/config";
import type { User, AuthResponse } from "@/entities/user/model";

interface AuthState {
  user: User | null;
  accessToken: string | null;
  refreshToken: string | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  error: string | null;

  // Actions
  setAuth: (response: AuthResponse) => void;
  clearAuth: () => void;
  setUser: (user: User | null) => void;
  setLoading: (loading: boolean) => void;
  setError: (error: string | null) => void;
  logout: () => void;
}

const AUTH_STORAGE_KEY = "auth-storage";

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      user: null,
      accessToken: null,
      refreshToken: null,
      isAuthenticated: false,
      isLoading: false,
      error: null,

      setAuth: (response: AuthResponse) => {
        localStorage.setItem(STORAGE_KEYS.accessToken, response.access_token);
        localStorage.setItem(STORAGE_KEYS.refreshToken, response.refresh_token);
        set({
          user: response.user,
          accessToken: response.access_token,
          refreshToken: response.refresh_token,
          isAuthenticated: true,
          error: null,
        });
      },

      clearAuth: () => {
        localStorage.removeItem(STORAGE_KEYS.accessToken);
        localStorage.removeItem(STORAGE_KEYS.refreshToken);
        localStorage.removeItem(AUTH_STORAGE_KEY);
        set({
          user: null,
          accessToken: null,
          refreshToken: null,
          isAuthenticated: false,
          error: null,
        });
      },

      setUser: (user) => set({ user, isAuthenticated: !!user }),
      setLoading: (isLoading) => set({ isLoading }),
      setError: (error) => set({ error }),

      logout: () => {
        localStorage.removeItem(STORAGE_KEYS.accessToken);
        localStorage.removeItem(STORAGE_KEYS.refreshToken);
        localStorage.removeItem(AUTH_STORAGE_KEY);
        set({
          user: null,
          accessToken: null,
          refreshToken: null,
          isAuthenticated: false,
          error: null,
        });
      },
    }),
    {
      name: AUTH_STORAGE_KEY,
      // Do not persist isAuthenticated; derive it from tokens on rehydration.
      // This prevents a stale "authenticated" flag when localStorage tokens
      // were cleared (e.g. by the API client after a 401) but the persisted
      // storage still contains the old flag.
      partialize: (state) => ({
        user: state.user,
        accessToken: state.accessToken,
        refreshToken: state.refreshToken,
      }),
      onRehydrateStorage: () => (state) => {
        if (!state) return;

        const hasAccessToken = !!state.accessToken;
        const hasRefreshToken = !!state.refreshToken;

        if (!hasAccessToken || !hasRefreshToken) {
          // Tokens are missing or incomplete -> treat as logged out.
          state.user = null;
          state.accessToken = null;
          state.refreshToken = null;
          state.isAuthenticated = false;
        } else {
          state.isAuthenticated = true;
        }
      },
    }
  )
);
