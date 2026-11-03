import { create } from 'zustand'

import type { User } from './types'

type SessionStatus = 'unknown' | 'auth' | 'anonymous'

interface SessionState {
  user: User | null
  accessToken: string | null
  expiresAt: number
  status: SessionStatus
  setSession: (user: User, accessToken: string, expiresIn: number) => void
  setToken: (accessToken: string, expiresIn: number) => void
  setUser: (user: User) => void
  setAnonymous: () => void
  clear: () => void
}

export const useSession = create<SessionState>()((set) => ({
  user: null,
  accessToken: null,
  expiresAt: 0,
  status: 'unknown',
  setSession: (user, accessToken, expiresIn) =>
    set({ user, accessToken, expiresAt: Date.now() + expiresIn * 1000, status: 'auth' }),
  setToken: (accessToken, expiresIn) =>
    set({ accessToken, expiresAt: Date.now() + expiresIn * 1000 }),
  setUser: (user) => set({ user }),
  setAnonymous: () => set({ user: null, accessToken: null, expiresAt: 0, status: 'anonymous' }),
  clear: () => set({ user: null, accessToken: null, expiresAt: 0, status: 'anonymous' }),
}))

export const getSession = () => useSession.getState()
