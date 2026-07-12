import { create } from 'zustand'
import { persist } from 'zustand/middleware'

export interface User {
  id: number
  name: string
  email: string
  phone?: string
  roles: string[]
  is_nca_verified?: boolean
  iin?: string | null
  oferta_signed?: boolean
}

interface AppState {
  token: string | null
  user: User | null
  authOpen: boolean
  authMode: 'login' | 'register'
  ncaOpen: boolean
  ofertaOpen: boolean
  setToken: (t: string | null) => void
  setUser: (u: User | null) => void
  logout: () => void
  openAuth: (mode?: 'login' | 'register') => void
  closeAuth: () => void
  openNCA: () => void
  closeNCA: () => void
  openOferta: () => void
  closeOferta: () => void
}

export const useStore = create<AppState>()(
  persist(
    (set) => ({
      token: null,
      user: null,
      authOpen: false,
      authMode: 'login',
      ncaOpen: false,
      ofertaOpen: false,
      setToken: (token) => set({ token }),
      setUser: (user) => set({ user }),
      logout: () => set({ token: null, user: null }),
      openAuth: (mode = 'login') => set({ authOpen: true, authMode: mode }),
      closeAuth: () => set({ authOpen: false }),
      openNCA: () => set({ ncaOpen: true }),
      closeNCA: () => set({ ncaOpen: false }),
      openOferta: () => set({ ofertaOpen: true }),
      closeOferta: () => set({ ofertaOpen: false }),
    }),
    { name: 'marqet-auth', partialize: (s) => ({ token: s.token, user: s.user }) }
  )
)
