import type {
  Alert, AuditRecord, ConfigPushRequest, ConfigPushResult, ConfigVersion,
  ConfigTemplate, ConfigTemplateCreate, ConfigTemplateRenderRequest,
  ConfigVersionDetail, Device, DeviceCreate, DeviceMetrics, DeviceStatus,
  Interface, LogQuery, LogRecord, NetworkMetrics, TimeWindow, TopologyLink,
  CurrentUser, UserAccount, UserCreate, UserUpdate,
  DnsRecord, DnsRecordCreate, DnsRecordUpdate, DnsZone, DnsZoneCreate,
  DhcpLease, DhcpPool, DhcpPoolCreate, DhcpPoolUpdate, DhcpReservation, DhcpReservationCreate,
} from './types'
import { UNAUTHORIZED_EVENT } from './session'

const base = '/api/v1'

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${base}${path}`, {
    ...init,
    headers: { Accept: 'application/json', 'Content-Type': 'application/json', ...init.headers },
  })
  if (response.status === 401 && path !== '/auth/login') {
    // Session missing or expired: tell the app to show the Login screen (R7.1).
    window.dispatchEvent(new Event(UNAUTHORIZED_EVENT))
  }
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

// The server records the logged-in user as the operator (R3.3, ADR-0005).
export function retrieveConfig(deviceId: number): Promise<ConfigVersion> {
  return request(`/devices/${deviceId}/config/retrieve`, { method: 'POST' })
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

export function restoreConfig(deviceId: number, version: number): Promise<ConfigPushResult> {
  return request(`/devices/${deviceId}/config/versions/${version}/restore`, { method: 'POST' })
}

export function listConfigTemplates(): Promise<ConfigTemplate[]> {
  return request('/configuration-templates')
}

export function createConfigTemplate(payload: ConfigTemplateCreate): Promise<ConfigTemplate> {
  return request('/configuration-templates', { method: 'POST', body: JSON.stringify(payload) })
}

export function updateConfigTemplate(
  templateId: number, patch: Partial<ConfigTemplateCreate>,
): Promise<ConfigTemplate> {
  return request(`/configuration-templates/${templateId}`, { method: 'PATCH', body: JSON.stringify(patch) })
}

export function deleteConfigTemplate(templateId: number): Promise<void> {
  return request(`/configuration-templates/${templateId}`, { method: 'DELETE' })
}

export function renderConfigTemplate(
  payload: ConfigTemplateRenderRequest,
): Promise<{ configuration: string }> {
  return request('/configuration-templates/render', { method: 'POST', body: JSON.stringify(payload) })
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

// --- Authentication and accounts (R7.1, R7.4; ADR-0005) ---------------------------------------

export function login(username: string, password: string): Promise<CurrentUser> {
  return request('/auth/login', { method: 'POST', body: JSON.stringify({ username, password }) })
}

export function logout(): Promise<void> {
  return request('/auth/logout', { method: 'POST' })
}

export function me(): Promise<CurrentUser> {
  return request('/auth/me')
}

export function listUsers(): Promise<UserAccount[]> {
  return request('/users')
}

export function createUser(payload: UserCreate): Promise<UserAccount> {
  return request('/users', { method: 'POST', body: JSON.stringify(payload) })
}

export function updateUser(userId: number, patch: UserUpdate): Promise<UserAccount> {
  return request(`/users/${userId}`, { method: 'PATCH', body: JSON.stringify(patch) })
}

// --- DNS (R5.2) -------------------------------------------------------------------------------

export function listDnsZones(): Promise<DnsZone[]> {
  return request('/dns/zones')
}

export function createDnsZone(payload: DnsZoneCreate): Promise<DnsZone> {
  return request('/dns/zones', { method: 'POST', body: JSON.stringify(payload) })
}

export function updateDnsZone(zoneId: number, defaultTtl: number): Promise<DnsZone> {
  return request(`/dns/zones/${zoneId}`, { method: 'PATCH', body: JSON.stringify({ default_ttl: defaultTtl }) })
}

export function deleteDnsZone(zoneId: number): Promise<void> {
  return request(`/dns/zones/${zoneId}`, { method: 'DELETE' })
}

export function listDnsRecords(zoneId: number): Promise<DnsRecord[]> {
  return request(`/dns/zones/${zoneId}/records`)
}

export function createDnsRecord(zoneId: number, payload: DnsRecordCreate): Promise<DnsRecord> {
  return request(`/dns/zones/${zoneId}/records`, { method: 'POST', body: JSON.stringify(payload) })
}

export function updateDnsRecord(recordId: number, patch: DnsRecordUpdate): Promise<DnsRecord> {
  return request(`/dns/records/${recordId}`, { method: 'PATCH', body: JSON.stringify(patch) })
}

export function deleteDnsRecord(recordId: number): Promise<void> {
  return request(`/dns/records/${recordId}`, { method: 'DELETE' })
}

// --- DHCP (R6.2-R6.4) -------------------------------------------------------------------------

export function listDhcpPools(): Promise<DhcpPool[]> {
  return request('/dhcp/pools')
}

export function createDhcpPool(payload: DhcpPoolCreate): Promise<DhcpPool> {
  return request('/dhcp/pools', { method: 'POST', body: JSON.stringify(payload) })
}

export function updateDhcpPool(poolId: number, patch: DhcpPoolUpdate): Promise<DhcpPool> {
  return request(`/dhcp/pools/${poolId}`, { method: 'PATCH', body: JSON.stringify(patch) })
}

export function deleteDhcpPool(poolId: number): Promise<void> {
  return request(`/dhcp/pools/${poolId}`, { method: 'DELETE' })
}

export function listDhcpReservations(poolId: number): Promise<DhcpReservation[]> {
  return request(`/dhcp/pools/${poolId}/reservations`)
}

export function createDhcpReservation(poolId: number, payload: DhcpReservationCreate): Promise<DhcpReservation> {
  return request(`/dhcp/pools/${poolId}/reservations`, { method: 'POST', body: JSON.stringify(payload) })
}

export function deleteDhcpReservation(reservationId: number): Promise<void> {
  return request(`/dhcp/reservations/${reservationId}`, { method: 'DELETE' })
}

export function listDhcpLeases(poolId?: number): Promise<DhcpLease[]> {
  return request(poolId === undefined ? '/dhcp/leases' : `/dhcp/leases?pool_id=${poolId}`)
}

export function releaseDhcpLease(leaseId: number): Promise<void> {
  return request(`/dhcp/leases/${leaseId}`, { method: 'DELETE' })
}
