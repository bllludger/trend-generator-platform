import { create } from 'zustand'

interface AuthState {
  isAuthenticated: boolean
  token: string | null
  user: { username: string } | null
  login: (token: string, user: { username: string }) => void
  logout: () => void
}

export const useAuthStore = create<AuthState>((set) => ({
  isAuthenticated: !!localStorage.getItem('access_token'),
  token: localStorage.getItem('access_token'),
  user: null,
  
  login: (token, user) => {
    localStorage.setItem('access_token', token)
    set({ isAuthenticated: true, token, user })
  },
  
  logout: () => {
    localStorage.removeItem('access_token')
    set({ isAuthenticated: false, token: null, user: null })
  },
}))
