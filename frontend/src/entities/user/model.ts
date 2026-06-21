export interface User {
  id: string;
  email: string;
  username: string;
  full_name?: string;
  is_active: boolean;
  created_at: string;
}

export interface UserCreate {
  email: string;
  username: string;
  password: string;
  full_name?: string;
}

export interface UserLogin {
  username: string;
  password: string;
}

export interface AuthResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  user: User;
}

export interface UserState {
  user: User | null;
  isAuthenticated: boolean;
  isLoading: boolean;
}
