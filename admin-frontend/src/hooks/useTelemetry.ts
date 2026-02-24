import { useQuery } from '@tanstack/react-query'
import { telemetryService } from '@/services/api'

export function useTelemetry(windowHours: number = 24) {
  return useQuery({
    queryKey: ['telemetry', windowHours],
    queryFn: () => telemetryService.getDashboard(windowHours),
    refetchInterval: 30000, // Refresh every 30 seconds
  })
}
