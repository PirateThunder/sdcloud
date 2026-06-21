import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { loginUser, registerUser, getMe } from "@/entities/user/api";
import { useAuthStore } from "./model";
import type { UserLogin, UserCreate } from "@/entities/user/model";

const AUTH_KEYS = {
  me: ["auth", "me"] as const,
};

export function useMe() {
  const { isAuthenticated } = useAuthStore();

  return useQuery({
    queryKey: AUTH_KEYS.me,
    queryFn: getMe,
    enabled: isAuthenticated,
    staleTime: 1000 * 60 * 5,
  });
}

export function useLogin() {
  const queryClient = useQueryClient();
  const router = useRouter();
  const { setAuth, setLoading, setError } = useAuthStore();

  return useMutation({
    mutationFn: (data: UserLogin) => {
      setLoading(true);
      setError(null);
      return loginUser(data);
    },
    onSuccess: (response) => {
      setAuth(response);
      queryClient.setQueryData(AUTH_KEYS.me, response.user);
      queryClient.invalidateQueries({ queryKey: AUTH_KEYS.me });
      router.push("/chat");
    },
    onError: (error: Error) => {
      setError(error.message || "Ошибка входа");
    },
    onSettled: () => {
      setLoading(false);
    },
  });
}

export function useRegister() {
  const queryClient = useQueryClient();
  const router = useRouter();
  const { setAuth, setLoading, setError } = useAuthStore();

  return useMutation({
    mutationFn: (data: UserCreate) => {
      setLoading(true);
      setError(null);
      return registerUser(data);
    },
    onSuccess: (response) => {
      setAuth(response);
      queryClient.setQueryData(AUTH_KEYS.me, response.user);
      router.push("/chat");
    },
    onError: (error: Error) => {
      setError(error.message || "Ошибка регистрации");
    },
    onSettled: () => {
      setLoading(false);
    },
  });
}

export function useLogout() {
  const queryClient = useQueryClient();
  const router = useRouter();
  const { logout } = useAuthStore();

  return () => {
    logout();
    queryClient.clear();
    router.push("/login");
  };
}
