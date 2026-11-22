export interface DeviceBase {
  name: string
  management_ip: string
  platform?: string
  ssh_port?: number
}

/** Credentials are write-only: sent on create/update, never returned (R1.4). */
export interface DeviceCreate extends DeviceBase {
  username?: string
  password?: string
  secret?: string
}

/** R1.3: test unsaved form values; credentials are used once and not stored. */
export type ConnectionTestRequest = Omit<DeviceCreate, 'name'>

export type ConnectionStage = 'reachability' | 'login' | 'enable'

export interface ConnectionTestResult {
  ok: boolean
  failed_stage: ConnectionStage | null
  message: string
  checks: { stage: ConnectionStage; ok: boolean; message: string }[]
}

export interface Device extends Required<DeviceBase> {
  id: number
  created_at: string
  has_credentials: boolean
}

export interface ConfigVersion {
  id: number
  device_id: number
  version: number
  source: string
  operator: string
  created_at: string
}

export interface ConfigVersionDetail extends ConfigVersion {
  configuration: string
}

export interface ConfigTemplate {
  id: number
  name: string
  configuration: string
  created_at: string
  updated_at: string
}

export interface ConfigTemplateCreate {
  name: string
  configuration: string
}

export interface ConfigTemplateRenderRequest {
  configuration: string
  variables: Record<string, string>
}

export interface ConfigPushRequest {
  device_ids: number[]
  configuration: string
}

/** Per-device push/rollback outcome; mirrors ChangeStatus in app/schemas.py (SRS 4.3.4 step 5). */
export type ChangeStatus =
  | 'succeeded' | 'unverified' | 'rejected' | 'unreachable' | 'credentials' | 'not_found' | 'failed'

export interface ConfigPushResult {
  device_id: number
  status: ChangeStatus
  before_version: number | null
  after_version: number | null
  error: string | null
}

export interface LogRecord {
  id: number
  timestamp: string
  received_at: string
  source: string
  facility: number | null
  severity: number | null
  body: string
  parsed: boolean
}

export interface AuditRecord {
  id: number
  occurred_at: string
  actor: string
  action: string
  outcome: string
  device_name: string | null
  detail: string
}

export interface LogQuery {
  query?: string
  source?: string
  severity?: number
  since?: string
  until?: string
  limit?: number
}

// Monitoring (Track A) — proposed contract
export interface TopologyLink {
  a: number
  b: number
}

export interface Interface {
  index: number
  name: string
  oper_status: 'up' | 'down'
  speed_mbps: number | null
}

export interface DeviceStatus {
  device_id: number
  state: 'up' | 'down'
  last_poll_at: string
  consecutive_failures: number
}

export interface Alert {
  id: number
  device_id: number
  message: string
  raised_at: string
}

export interface MetricPoint {
  t: string
  value: number
}

export type TimeWindow = '1h' | '24h' | '7d'

export interface NetworkMetrics {
  devices_up: MetricPoint[]
  cpu_avg: MetricPoint[]
  throughput_in_bps: MetricPoint[]
  throughput_out_bps: MetricPoint[]
}

export interface DeviceMetrics {
  cpu: MetricPoint[]
  memory: MetricPoint[]
  throughput_in_bps: MetricPoint[]
  throughput_out_bps: MetricPoint[]
}

/** Signed-in user (GET /auth/me, POST /auth/login). Roles per SRS 2.3 / ADR-0005. */
export type Role = 'admin' | 'viewer'

export interface CurrentUser {
  id: number
  username: string
  role: Role
  created_at: string
}

export interface UserAccount extends CurrentUser {
  disabled: boolean
}

export interface UserCreate {
  username: string
  password: string
  role: Role
}

export interface UserUpdate {
  role?: Role
  disabled?: boolean
  password?: string
}

/** DNS zones and records (SRS 4.5; contracts.md "DNS service"). */
export type DnsRecordType = 'A' | 'AAAA' | 'CNAME' | 'PTR'

export interface DnsZone {
  id: number
  name: string
  default_ttl: number
  serial: number
  record_count: number
  created_at: string
  updated_at: string
}

export interface DnsZoneCreate {
  name: string
  default_ttl?: number
}

export interface DnsRecord {
  id: number
  zone_id: number
  name: string
  fqdn: string
  rtype: DnsRecordType
  value: string
  ttl: number | null
  created_at: string
}

export interface DnsRecordCreate {
  name: string
  rtype: DnsRecordType
  value: string
  ttl?: number | null
}

/** Omitted fields are unchanged; `ttl: null` resets to the zone default. */
export interface DnsRecordUpdate {
  name?: string
  value?: string
  ttl?: number | null
}

/** DHCP pools, reservations and leases (SRS 4.6; contracts.md "DHCP service"). */
export interface DhcpPool {
  id: number
  name: string
  subnet: string
  range_start: string
  range_end: string
  gateway: string
  dns_servers: string[]
  domain: string
  lease_seconds: number
  reservation_count: number
  active_lease_count: number
  created_at: string
  updated_at: string
}

export interface DhcpPoolCreate {
  name: string
  subnet: string
  range_start: string
  range_end: string
  gateway: string
  dns_servers: string[]
  domain: string
  lease_seconds: number
}

export type DhcpPoolUpdate = Partial<DhcpPoolCreate>

export interface DhcpReservation {
  id: number
  pool_id: number
  mac: string
  ip: string
  hostname: string | null
  created_at: string
}

export interface DhcpReservationCreate {
  mac: string
  ip: string
  hostname?: string | null
}

export interface DhcpLease {
  id: number
  pool_id: number
  pool_name: string
  mac: string
  ip: string
  hostname: string | null
  state: 'offered' | 'bound'
  expires_at: string
}
