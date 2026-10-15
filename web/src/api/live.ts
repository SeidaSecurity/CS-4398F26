import type {
  Alert, AuditRecord, ConfigPushRequest, ConfigPushResult, ConfigVersion,
  ConfigVersionDetail, Device, DeviceCreate, DeviceMetrics, DeviceStatus,
  Interface, LogQuery, LogRecord, NetworkMetrics, TimeWindow, TopologyLink,
} from './types'

const base = '/api/v1'

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${base}${path}`, {
    ...init,
    headers: { Accept: 'application/json', 'Content-Type': 'application/json', ...init.headers },
  })
  if (!response.ok) {
    const payload: unknown = await response.json().catch(() => null)
    const detail = payload && typeof payload === 'object' && 'detail' in payload
      ? payload.detail
      : response.statusText || `HTTP ${response.status}`
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
  }
  if (response.status === 204) return undefined as T
  const body = await response.text()
  return body.trim() ? JSON.parse(body) as T : undefined as T
}

export function listDevices(): Promise<Device[]> {
  return request('/devices')
}

export function createDevice(device: DeviceCreate): Promise<Device> {
  return request('/devices', { method: 'POST', body: JSON.stringify(device) })
}

export function updateDevice(deviceId: number, patch: Partial<DeviceCreate>): Promise<Device> {
  return request(`/devices/${deviceId}`, { method: 'PATCH', body: JSON.stringify(patch) })
}

export function deleteDevice(deviceId: number): Promise<void> {
  return request(`/devices/${deviceId}`, { method: 'DELETE' })
}

export function retrieveConfig(deviceId: number, operator: string = 'unknown'): Promise<ConfigVersion> {
  const params = new URLSearchParams({ operator })
  return request(`/devices/${deviceId}/config/retrieve?${params}`, { method: 'POST' })
}

export function listConfigVersions(deviceId: number): Promise<ConfigVersion[]> {
  return request(`/devices/${deviceId}/config/versions`)
}

export function getConfigVersion(deviceId: number, version: number): Promise<ConfigVersionDetail> {
  return request(`/devices/${deviceId}/config/versions/${version}`)
}

export function pushConfig(req: ConfigPushRequest): Promise<ConfigPushResult[]> {
  return request('/configurations/push', { method: 'POST', body: JSON.stringify(req) })
}

export function searchLogs(q: LogQuery): Promise<LogRecord[]> {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(q)) {
    if (value !== undefined && value !== null) params.set(key, String(value))
  }
  return request(`/logs${params.size ? `?${params}` : ''}`)
}

export function listAudit(): Promise<AuditRecord[]> {
  return request('/audit')
}

export function listDeviceStatus(): Promise<DeviceStatus[]> {
  return request('/monitoring/status')
}

export function getTopology(): Promise<TopologyLink[]> {
  return request('/monitoring/topology')
}

export function listInterfaces(deviceId: number): Promise<Interface[]> {
  return request(`/monitoring/devices/${deviceId}/interfaces`)
}

export function listAlerts(): Promise<Alert[]> {
  return request('/monitoring/alerts')
}

export function getNetworkMetrics(window: TimeWindow): Promise<NetworkMetrics> {
  return request(`/monitoring/metrics?${new URLSearchParams({ window })}`)
}

export function getDeviceMetrics(deviceId: number, window: TimeWindow): Promise<DeviceMetrics> {
  return request(`/monitoring/devices/${deviceId}/metrics?${new URLSearchParams({ window })}`)
}
