import axios from 'axios'

const API_BASE = import.meta.env.VITE_API_BASE || '/api'

export const api = axios.create({
  baseURL: API_BASE,
  timeout: 30000, // 30s — тяжёлые эндпоинты телеметрии/аналитики
  headers: {
    'Content-Type': 'application/json',
  },
  withCredentials: true,
})

// Interceptor: токен + для FormData не задавать Content-Type (axios подставит multipart с boundary)
api.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('access_token')
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    if (config.data instanceof FormData) {
      delete (config.headers as Record<string, unknown>)['Content-Type']
    }
    return config
  },
  (error) => Promise.reject(error)
)

// Retry on network/timeout (once, after 2s)
api.interceptors.response.use(
  (response) => response,
  async (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('access_token')
      window.location.href = '/login'
      return Promise.reject(error)
    }
    const config = error.config
    if (!config || config.__retried) return Promise.reject(error)
    const isRetryable =
      !error.response ||
      error.code === 'ECONNABORTED' ||
      error.code === 'ERR_NETWORK' ||
      (error.response?.status >= 500 && error.response?.status < 600)
    if (isRetryable && (config.method === 'get' || config.method === 'GET')) {
      config.__retried = true
      await new Promise((r) => setTimeout(r, 2000))
      return api.request(config)
    }
    return Promise.reject(error)
  }
)

export default api
