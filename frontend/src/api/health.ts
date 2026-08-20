import { getJson } from './client'

export interface HealthData {
  status: 'healthy'
}

export function getBackendHealth(signal?: AbortSignal) {
  return getJson<HealthData>('/health', signal)
}
