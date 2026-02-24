import { useMutation } from '@tanstack/react-query'
import { authService } from '@/services/api'
import { useAuthStore } from '@/stores/authStore'
import { useNavigate } from 'react-router-dom'
import { toast } from 'sonner'

export function useAuth() {
  const navigate = useNavigate()
  const { login: setAuth, logout: clearAuth, isAuthenticated, user } = useAuthStore()

  const loginMutation = useMutation({
    mutationFn: ({ username, password }: { username: string; password: string }) =>
      authService.login(username, password),
    onSuccess: (data) => {
      setAuth(data.access_token, data.user)
      toast.success('Вход выполнен успешно!')
      navigate('/')
    },
    onError: (error: any) => {
      const status = error.response?.status
      const detail = error.response?.data?.detail
      if (status === 429) {
        toast.error(detail || 'Слишком много попыток входа. Подождите 15 минут.')
      } else {
        toast.error(typeof detail === 'string' ? detail : 'Ошибка входа')
      }
    },
  })

  const logoutMutation = useMutation({
    mutationFn: authService.logout,
    onSuccess: () => {
      clearAuth()
      navigate('/login')
      toast.success('Вы вышли из системы')
    },
  })

  return {
    isAuthenticated,
    user,
    login: loginMutation.mutate,
    logout: logoutMutation.mutate,
    isLoggingIn: loginMutation.isPending,
    isLoggingOut: logoutMutation.isPending,
  }
}
