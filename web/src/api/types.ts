export interface DeviceCreate {
  name: string
  management_ip: string
  platform?: string
  ssh_port?: number
}

export interface Device extends Required<DeviceCreate> {
  id: number
  created_at: string
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
  operator?: string
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
