import { apiClient, publicClient } from "@/shared/api/client";
import type { User, UserCreate, UserLogin, AuthResponse } from "./model";

export async function getMe(): Promise<User> {
  return apiClient.get("auth/me").json<User>();
}

export async function registerUser(data: UserCreate): Promise<AuthResponse> {
  return publicClient
    .post("auth/register", { json: data })
    .json<AuthResponse>();
}

export async function loginUser(data: UserLogin): Promise<AuthResponse> {
  const formData = new URLSearchParams();
  formData.append("username", data.username);
  formData.append("password", data.password);

  return publicClient
    .post("auth/login", {
      body: formData,
      headers: {
        "Content-Type": "application/x-www-form-urlencoded",
      },
    })
    .json<AuthResponse>();
}

export async function refreshToken(
  refreshToken: string
): Promise<{ access_token: string }> {
  return publicClient
    .post("auth/refresh", { json: { refresh_token: refreshToken } })
    .json<{ access_token: string }>();
}
