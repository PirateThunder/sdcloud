import ky from "ky";
import { STORAGE_KEYS, API_BASE_URL } from "@/shared/config";

const AUTH_STORAGE_KEY = "auth-storage";

function clearAuthStorage(): void {
  localStorage.removeItem(STORAGE_KEYS.accessToken);
  localStorage.removeItem(STORAGE_KEYS.refreshToken);
  localStorage.removeItem(AUTH_STORAGE_KEY);
}

export const apiClient = ky.create({
  prefixUrl: `${API_BASE_URL}/api/v1`,
  timeout: 60000,
  headers: {
    "Content-Type": "application/json",
  },
  hooks: {
    beforeRequest: [
      (request) => {
        const token = localStorage.getItem(STORAGE_KEYS.accessToken);
        if (token) {
          request.headers.set("Authorization", `Bearer ${token}`);
        }
      },
    ],
    afterResponse: [
      async (request, options, response) => {
        if (response.status === 401) {
          const accessToken = localStorage.getItem(STORAGE_KEYS.accessToken);
          const refreshToken = localStorage.getItem(STORAGE_KEYS.refreshToken);

          if (!refreshToken) {
            if (accessToken) {
              // Inconsistent auth state: access token exists but refresh token is missing.
              clearAuthStorage();
              window.location.href = "/login";
              return response;
            }

            // No tokens means the user is not logged in (guest mode).
            // Don't redirect to login; let the caller handle the 401.
            return response;
          }

          // Token expired - try to refresh
          try {
            const refreshResponse = await ky
              .post(`${API_BASE_URL}/api/v1/auth/refresh`, {
                json: { refresh_token: refreshToken },
              })
              .json<{ access_token: string }>();

            localStorage.setItem(
              STORAGE_KEYS.accessToken,
              refreshResponse.access_token
            );

            // Retry original request
            return ky(request);
          } catch {
            // Refresh failed, clear tokens and redirect to login
            clearAuthStorage();
            window.location.href = "/login";
          }
        }
        return response;
      },
    ],
  },
});

export const publicClient = ky.create({
  prefixUrl: `${API_BASE_URL}/api/v1`,
  timeout: 30000,
  headers: {
    "Content-Type": "application/json",
  },
});
