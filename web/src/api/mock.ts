import type {
  Alert, AuditRecord, ConfigPushRequest, ConfigPushResult, ConfigVersion,
  ConfigTemplate, ConfigTemplateCreate, ConfigTemplateRenderRequest,
  ConfigVersionDetail, Device, DeviceCreate, DeviceMetrics, DeviceStatus,
  Interface, LogQuery, LogRecord, MetricPoint, NetworkMetrics, TimeWindow, TopologyLink,
} from './types'
import { deviceKind } from '../components/devices'

const hour = 3_600_000
const epoch = Date.now()
const delay = () => new Promise<void>(resolve => setTimeout(resolve, 150))
const iso = (time: number) => new Date(time).toISOString()
const copy = <T,>(value: T): T => structuredClone(value)

function prng(seed: number) {
  let state = seed >>> 0
  return () => {
    state = (Math.imul(1664525, state) + 1013904223) >>> 0
    return state / 4294967296
  }
}

const devices: Device[] = [
  ['R1-core', '10.0.0.1'],
  ['R2-edge', '10.0.0.2'],
  ['SW1-access', '10.0.1.1'],
  ['SW2-access', '10.0.1.2'],
  ['R3-branch', '10.0.2.1'],
  ['FW1', '10.0.0.254'],
].map(([name, management_ip], index) => ({
  id: index + 1,
  name,
  management_ip,
  platform: 'cisco_ios',
  ssh_port: 22,
  created_at: iso(epoch - (30 - index) * 24 * hour),
}))

const statuses: DeviceStatus[] = devices.map(device => ({
  device_id: device.id,
  state: device.id === 5 ? 'down' : 'up',
  last_poll_at: iso(epoch - 30_000),
  consecutive_failures: device.id === 5 ? 2 : 0,
}))

const topology: TopologyLink[] = [
  { a: 6, b: 1 },
  { a: 6, b: 2 },
  { a: 1, b: 2 },
  { a: 1, b: 3 },
  { a: 1, b: 4 },
  { a: 2, b: 4 },
  { a: 2, b: 5 },
]

const alerts: Alert[] = [{
  id: 1,
  device_id: 5,
  message: 'No response to 2 consecutive polls',
  raised_at: iso(epoch - 70 * 60_000),
}]

const versions = new Map<number, ConfigVersionDetail[]>()
const audit: AuditRecord[] = []
const configurationTemplates: ConfigTemplate[] = []
let nextConfigId = 1
let nextAuditId = 1
let nextDeviceId = 7
let nextTemplateId = 1

function runningConfig(device: Device, revision: number): string {
  const subnet = device.management_ip.split('.').slice(0, 3).join('.')
  return [
    'version 15.2',
    'service timestamps log datetime msec',
    `hostname ${device.name}`,
    '!',
    'interface Loopback0',
    ` ip address 10.255.0.${device.id} 255.255.255.255`,
    '!',
    'interface GigabitEthernet0/0',
    ` description Management LAN - revision ${revision}`,
    ...(device.name.startsWith('SW') ? [' no switchport'] : []),
    ` ip address ${device.management_ip} 255.255.255.0`,
    ' no shutdown',
    '!',
    'interface GigabitEthernet0/1',
    ' description OSPF uplink',
    ...(device.name.startsWith('SW') ? [' no switchport'] : []),
    ` ip address 172.16.${device.id}.1 255.255.255.252`,
    ` ip ospf cost ${10 * revision}`,
    ' no shutdown',
    '!',
    'router ospf 1',
    ` router-id 10.255.0.${device.id}`,
    ` network ${subnet}.0 0.0.0.255 area 0`,
    ` network 172.16.${device.id}.0 0.0.0.3 area 0`,
    ' passive-interface GigabitEthernet0/0',
    '!',
    `logging buffered ${4096 * revision} informational`,
    'end',
  ].join('\n')
}

function saveVersion(
  deviceId: number, configuration: string, source: string, operator: string,
  createdAt = iso(Date.now()),
): ConfigVersionDetail {
  const history = versions.get(deviceId) ?? []
  const record: ConfigVersionDetail = {
    id: nextConfigId++,
    device_id: deviceId,
    version: (history.at(-1)?.version ?? 0) + 1,
    source,
    operator,
    created_at: createdAt,
    configuration,
  }
  history.push(record)
  versions.set(deviceId, history)
  return record
}

function recordAudit(
  actor: string, action: string, outcome: string, deviceName: string | null,
  detail: string, occurredAt = iso(Date.now()),
) {
  audit.push({
    id: nextAuditId++, occurred_at: occurredAt, actor, action, outcome,
    device_name: deviceName, detail,
  })
}

function summary(record: ConfigVersionDetail): ConfigVersion {
  const { configuration, ...metadata } = record
  void configuration
  return metadata
}

for (const device of devices) {
  for (let revision = 1; revision <= 2 + device.id % 2; revision++) {
    const createdAt = iso(epoch - (4 - revision) * 6 * hour - device.id * 60_000)
    const record = saveVersion(device.id, runningConfig(device, revision), 'retrieval', 'admin', createdAt)
    recordAudit('admin', 'configuration.retrieve', 'succeeded', device.name,
      `Saved configuration version ${record.version}`, createdAt)
  }
}

const logRandom = prng(4398)

function logTimes(count: number, start: number, duration: number): number[] {
  // Exponential interarrival gaps, scaled to fit the requested window.
  // The extra gap leaves some quiet time after the final message.
  const gaps = Array.from({ length: count + 1 }, () => -Math.log(1 - logRandom()))
  const total = gaps.reduce((sum, gap) => sum + gap, 0)
  let elapsed = 0
  return gaps.slice(0, count).map(gap => {
    elapsed += gap
    return Math.round(start + elapsed / total * duration)
  })
}

const logs: LogRecord[] = logTimes(180, epoch - 24 * hour, 24 * hour).map((timestamp, index) => {
  const device = devices[Math.floor(logRandom() * devices.length)]
  const messages = [
    { severity: 5, body: '%SYS-5-CONFIG_I: Configured from console by admin on vty0 (10.0.0.10)' },
    { severity: 5, body: `%OSPF-5-ADJCHG: Process 1, Nbr 10.255.0.${device.id % 6 + 1} on GigabitEthernet0/1 from LOADING to FULL, Loading Done` },
    { severity: 5, body: '%SEC_LOGIN-5-LOGIN_SUCCESS: Login Success [user: admin] [Source: 10.0.0.10] [localport: 22] at 12:00:00 UTC' },
    { severity: 6, body: '%LINEPROTO-6-UPDOWN: Line protocol on Interface GigabitEthernet0/1, changed state to up' },
    { severity: 6, body: '%SYS-6-LOGGINGHOST_STARTSTOP: Logging to host 10.0.0.10 port 514 started' },
  ]
  const message = index % 19 === 0
    ? { severity: 3, body: '%LINK-3-UPDOWN: Interface GigabitEthernet0/1, changed state to down' }
    : index % 31 === 0
      ? { severity: 4, body: '%SYS-4-CPUHOG: Task is running for (2000)msecs, process = IP Input' }
      : messages[Math.floor(logRandom() * messages.length)]
  return {
    id: index + 1,
    timestamp: iso(timestamp),
    received_at: iso(timestamp + 100),
    source: device.name,
    facility: 23,
    severity: message.severity,
    body: message.body,
    parsed: true,
  }
})

function addOutageLogs(deviceId: number, center: number, count: number) {
  const device = devices.find(device => device.id === deviceId)!
  const messages = [
    { severity: 3, body: '%LINK-3-UPDOWN: Interface GigabitEthernet0/1, changed state to down' },
    { severity: 4, body: '%SYS-4-CPUHOG: Task is running for (2000)msecs, process = IP Input' },
    { severity: 3, body: '%LINK-3-UPDOWN: Interface GigabitEthernet0/0, changed state to down' },
    { severity: 5, body: '%LINEPROTO-5-UPDOWN: Line protocol on Interface GigabitEthernet0/1, changed state to down' },
    { severity: 3, body: '%LINK-3-UPDOWN: Interface GigabitEthernet0/1, changed state to down' },
    { severity: 5, body: `%OSPF-5-ADJCHG: Process 1, Nbr 10.255.0.${device.id % 6 + 1} on GigabitEthernet0/1 from FULL to DOWN, Neighbor Down: Interface down or detached` },
  ]
  for (const [index, timestamp] of logTimes(count, center - 150_000, 300_000).entries()) {
    const message = messages[index % messages.length]
    logs.push({
      id: logs.length + 1,
      timestamp: iso(timestamp),
      received_at: iso(timestamp + 100),
      source: device.name,
      facility: 23,
      severity: message.severity,
      body: message.body,
      parsed: true,
    })
  }
}

addOutageLogs(5, epoch - 70 * 60_000, 12)
addOutageLogs(4, epoch - 14 * hour, 8)

function requireDevice(deviceId: number): Device {
  const device = devices.find(device => device.id === deviceId)
  if (!device) throw new Error('Device not found')
  return device
}

function validateText(value: string, maximum: number, field: string) {
  if (typeof value !== 'string' || value.length < 1 || value.length > maximum) {
    throw new Error(`${field} must contain between 1 and ${maximum} characters`)
  }
}

export async function listDevices(): Promise<Device[]> {
  await delay()
  return copy([...devices].sort((a, b) => a.name < b.name ? -1 : a.name > b.name ? 1 : 0))
}

export async function createDevice(payload: DeviceCreate): Promise<Device> {
  await delay()
  validateText(payload.name, 120, 'name')
  validateText(payload.management_ip, 255, 'management_ip')
  validateText(payload.platform ?? 'cisco_ios', 80, 'platform')
  const port = payload.ssh_port ?? 22
  if (!Number.isInteger(port) || port < 1 || port > 65535) throw new Error('ssh_port must be between 1 and 65535')
  if (devices.some(device => device.name === payload.name)) {
    throw new Error('A device with that name already exists')
  }
  const device: Device = {
    name: payload.name, management_ip: payload.management_ip,
    platform: payload.platform ?? 'cisco_ios', ssh_port: port,
    id: nextDeviceId++, created_at: iso(Date.now()),
  }
  devices.push(device)
  statuses.push({ device_id: device.id, state: 'up', last_poll_at: iso(Date.now()), consecutive_failures: 0 })
  return copy(device)
}

export async function updateDevice(deviceId: number, patch: Partial<DeviceCreate>): Promise<Device> {
  await delay()
  const device = requireDevice(deviceId)
  const updated = {
    name: patch.name ?? device.name,
    management_ip: patch.management_ip ?? device.management_ip,
    platform: patch.platform ?? device.platform,
    ssh_port: patch.ssh_port ?? device.ssh_port,
  }
  validateText(updated.name, 120, 'name')
  validateText(updated.management_ip, 255, 'management_ip')
  validateText(updated.platform, 80, 'platform')
  if (!Number.isInteger(updated.ssh_port) || updated.ssh_port < 1 || updated.ssh_port > 65535) {
    throw new Error('ssh_port must be between 1 and 65535')
  }
  if (devices.some(other => other.id !== deviceId && other.name === updated.name)) {
    throw new Error('A device with that name already exists')
  }
  Object.assign(device, updated)
  return copy(device)
}

export async function deleteDevice(deviceId: number): Promise<void> {
  await delay()
  const device = requireDevice(deviceId)
  devices.splice(devices.indexOf(device), 1)
  for (let index = statuses.length - 1; index >= 0; index--) {
    if (statuses[index].device_id === deviceId) statuses.splice(index, 1)
  }
  for (let index = topology.length - 1; index >= 0; index--) {
    if (topology[index].a === deviceId || topology[index].b === deviceId) topology.splice(index, 1)
  }
  for (let index = alerts.length - 1; index >= 0; index--) {
    if (alerts[index].device_id === deviceId) alerts.splice(index, 1)
  }
  versions.delete(deviceId)
}

export async function retrieveConfig(deviceId: number, operator: string = 'unknown'): Promise<ConfigVersion> {
  await delay()
  validateText(operator, 120, 'operator')
  const device = requireDevice(deviceId)
  if (statuses.find(status => status.device_id === deviceId)?.state === 'down') {
    throw new Error('Configuration retrieval failed: Connection timed out')
  }
  const configuration = versions.get(deviceId)?.at(-1)?.configuration ?? runningConfig(device, 1)
  const record = saveVersion(deviceId, configuration, 'retrieval', operator)
  recordAudit(operator, 'configuration.retrieve', 'succeeded', device.name,
    `Saved configuration version ${record.version}`)
  return summary(record)
}

export async function listConfigVersions(deviceId: number): Promise<ConfigVersion[]> {
  await delay()
  requireDevice(deviceId)
  return (versions.get(deviceId) ?? []).map(summary).reverse()
}

export async function getConfigVersion(deviceId: number, version: number): Promise<ConfigVersionDetail> {
  await delay()
  const record = versions.get(deviceId)?.find(record => record.version === version)
  if (!record) throw new Error('Configuration version not found')
  return copy(record)
}

export async function pushConfig(req: ConfigPushRequest): Promise<ConfigPushResult[]> {
  await delay()
  if (!req.device_ids.length) throw new Error('device_ids must contain at least one device')
  validateText(req.configuration, Number.MAX_SAFE_INTEGER, 'configuration')
  const operator = req.operator ?? 'unknown'
  validateText(operator, 120, 'operator')
  return [...new Set(req.device_ids)].map(deviceId => {
    const device = devices.find(device => device.id === deviceId)
    const result: ConfigPushResult = {
      device_id: deviceId, status: 'failed', before_version: null, after_version: null, error: null,
    }
    if (!device) {
      return {
        ...result,
        status: 'not_found',
        error: `Device ${deviceId} is not in the inventory. Refresh the device list and try again.`,
      }
    }
    if (statuses.find(status => status.device_id === deviceId)?.state === 'down') {
      recordAudit(operator, 'configuration.push', 'failed', device.name,
        'DeviceUnreachableError: Connection timed out')
      return { ...result, status: 'unreachable', error: unreachableMessage(device) }
    }
    const configuration = versions.get(deviceId)?.at(-1)?.configuration ?? runningConfig(device, 1)
    const before = saveVersion(deviceId, configuration, 'pre_push', operator)
    recordAudit(operator, 'configuration.push', 'started', device.name,
      `Saved pre-push configuration version ${before.version}`)
    const after = saveVersion(deviceId, `${configuration}\n${req.configuration}`, 'post_push', operator)
    recordAudit(operator, 'configuration.push', 'succeeded', device.name,
      `Configuration version ${after.version} captured after push`)
    return { ...result, status: 'succeeded', before_version: before.version, after_version: after.version }
  })
}

function unreachableMessage(device: Device): string {
  return `Could not reach ${device.name} at ${device.management_ip}:${device.ssh_port}. `
    + 'Check that the device is powered on and SSH is enabled.'
}

export async function restoreConfig(
  deviceId: number, version: number, operator: string = 'unknown',
): Promise<ConfigPushResult> {
  await delay()
  validateText(operator, 120, 'operator')
  const device = requireDevice(deviceId)
  const target = versions.get(deviceId)?.find(record => record.version === version)
  if (!target) throw new Error('Configuration version not found')
  const result: ConfigPushResult = {
    device_id: deviceId, status: 'failed', before_version: null, after_version: null, error: null,
  }
  if (statuses.find(status => status.device_id === deviceId)?.state === 'down') {
    recordAudit(operator, 'configuration.rollback', 'failed', device.name,
      `Failed to restore configuration version ${version}: DeviceUnreachableError: Connection timed out`)
    return { ...result, status: 'unreachable', error: unreachableMessage(device) }
  }
  const current = versions.get(deviceId)?.at(-1)?.configuration ?? runningConfig(device, 1)
  const before = saveVersion(deviceId, current, 'pre_rollback', operator)
  recordAudit(operator, 'configuration.rollback', 'started', device.name,
    `Saved pre-rollback configuration version ${before.version}`)
  const after = saveVersion(deviceId, target.configuration, 'rollback', operator)
  recordAudit(operator, 'configuration.rollback', 'succeeded', device.name,
    `Restored configuration version ${version} as version ${after.version}`)
  return {
    ...result,
    status: 'succeeded',
    before_version: before.version,
    after_version: after.version,
  }
}

export async function listConfigTemplates(): Promise<ConfigTemplate[]> {
  await delay()
  return copy([...configurationTemplates].sort((a, b) => a.name.localeCompare(b.name)))
}

export async function createConfigTemplate(payload: ConfigTemplateCreate): Promise<ConfigTemplate> {
  await delay()
  validateText(payload.name.trim(), 120, 'name')
  validateText(payload.configuration, 100_000, 'configuration')
  if (configurationTemplates.some(template => template.name === payload.name.trim())) {
    throw new Error('A configuration template with that name already exists')
  }
  const now = iso(Date.now())
  const template = {
    id: nextTemplateId++,
    name: payload.name.trim(),
    configuration: payload.configuration,
    created_at: now,
    updated_at: now,
  }
  configurationTemplates.push(template)
  return copy(template)
}

export async function updateConfigTemplate(
  templateId: number, patch: Partial<ConfigTemplateCreate>,
): Promise<ConfigTemplate> {
  await delay()
  const template = configurationTemplates.find(item => item.id === templateId)
  if (!template) throw new Error('Configuration template not found')
  const name = patch.name === undefined ? template.name : patch.name.trim()
  const configuration = patch.configuration ?? template.configuration
  validateText(name, 120, 'name')
  validateText(configuration, 100_000, 'configuration')
  if (configurationTemplates.some(item => item.id !== templateId && item.name === name)) {
    throw new Error('A configuration template with that name already exists')
  }
  template.name = name
  template.configuration = configuration
  template.updated_at = iso(Date.now())
  return copy(template)
}

export async function deleteConfigTemplate(templateId: number): Promise<void> {
  await delay()
  const index = configurationTemplates.findIndex(item => item.id === templateId)
  if (index < 0) throw new Error('Configuration template not found')
  configurationTemplates.splice(index, 1)
}

export async function renderConfigTemplate(
  payload: ConfigTemplateRenderRequest,
): Promise<{ configuration: string }> {
  await delay()
  const matches = [...payload.configuration.matchAll(/\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}/g)]
  const remainder = payload.configuration.replace(/\{\{\s*[A-Za-z_][A-Za-z0-9_]*\s*\}\}/g, '')
  if (remainder.includes('{{') || remainder.includes('}}')) {
    throw new Error('Use placeholders in the form {{ variable_name }} with letters, numbers, and underscores')
  }
  const required = new Set(matches.map(match => match[1]))
  const supplied = new Set(Object.keys(payload.variables))
  const missing = [...required].filter(name => !supplied.has(name)).sort()
  const extra = [...supplied].filter(name => !required.has(name)).sort()
  if (missing.length) throw new Error(`Missing template values: ${missing.join(', ')}`)
  if (extra.length) throw new Error(`Unused template values: ${extra.join(', ')}`)
  return {
    configuration: payload.configuration.replace(
      /\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}/g,
      (_, name: string) => payload.variables[name],
    ),
  }
}

export async function searchLogs(q: LogQuery): Promise<LogRecord[]> {
  await delay()
  const limit = q.limit ?? 100
  if (!Number.isInteger(limit) || limit < 1 || limit > 1000) throw new Error('limit must be between 1 and 1000')
  if (q.severity !== undefined && (!Number.isInteger(q.severity) || q.severity < 0 || q.severity > 7)) {
    throw new Error('severity must be between 0 and 7')
  }
  const since = q.since === undefined ? -Infinity : Date.parse(q.since)
  const until = q.until === undefined ? Infinity : Date.parse(q.until)
  if (Number.isNaN(since) || Number.isNaN(until)) throw new Error('Invalid datetime')
  if (since > until) throw new Error("'since' must be earlier than or equal to 'until'")
  const query = q.query
    ? new RegExp(q.query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&').replace(/%/g, '.*').replace(/_/g, '.'), 'is')
    : null
  return copy(logs.filter(log => (
    (!query || query.test(log.body)) &&
    (!q.source || log.source === q.source) &&
    (q.severity === undefined || log.severity === q.severity) &&
    Date.parse(log.timestamp) >= since && Date.parse(log.timestamp) <= until
  )).sort((a, b) => Date.parse(b.timestamp) - Date.parse(a.timestamp)).slice(0, limit))
}

export async function listAudit(): Promise<AuditRecord[]> {
  await delay()
  return copy([...audit].sort((a, b) => Date.parse(b.occurred_at) - Date.parse(a.occurred_at) || b.id - a.id).slice(0, 100))
}

export async function listDeviceStatus(): Promise<DeviceStatus[]> {
  await delay()
  return copy(statuses)
}

export async function getTopology(): Promise<TopologyLink[]> {
  await delay()
  return copy(topology)
}

export async function listInterfaces(deviceId: number): Promise<Interface[]> {
  await delay()
  const device = requireDevice(deviceId)
  const kind = deviceKind(device.name, device.platform)
  const count = kind === 'switch' ? 28 : kind === 'firewall' ? 8 : 4
  const random = prng(4398 + deviceId)
  const deviceUp = statuses.find(status => status.device_id === deviceId)?.state === 'up'
  return Array.from({ length: count }, (_, offset) => {
    const up = kind === 'switch' ? random() < 0.7 : offset < count - 1
    return {
      index: offset + 1,
      name: kind === 'switch'
        ? offset < 24 ? `GigabitEthernet1/0/${offset + 1}` : `TenGigabitEthernet1/1/${offset - 23}`
        : `GigabitEthernet0/${offset}`,
      oper_status: deviceUp && up ? 'up' : 'down',
      speed_mbps: kind === 'switch' && offset >= 24 ? 10_000 : 1_000,
    }
  })
}

export async function listAlerts(): Promise<Alert[]> {
  await delay()
  return copy(alerts)
}

const durations: Record<TimeWindow, number> = { '1h': hour, '24h': 24 * hour, '7d': 7 * 24 * hour }

const metricOutages = [
  { deviceId: 5, start: epoch - 70 * 60_000, end: Infinity },
  { deviceId: 4, start: epoch - 14 * hour - 10 * 60_000, end: epoch - 14 * hour + 10 * 60_000 },
  { deviceId: 2, start: epoch - 3 * 24 * hour - 5 * 60_000, end: epoch - 3 * 24 * hour + 5 * 60_000 },
]

function deviceDownAt(deviceId: number, time: number): boolean {
  return metricOutages.some(outage => outage.deviceId === deviceId && time >= outage.start && time < outage.end)
}

function metricTimes(window: TimeWindow): number[] {
  const duration = durations[window]
  const start = epoch - duration
  const times = new Set(Array.from({ length: 96 }, (_, index) => start + index * duration / 95))
  // Include brief outages even when the regular samples are hours apart.
  for (const outage of metricOutages) {
    for (const time of [outage.start, outage.end]) {
      if (time >= start && time <= epoch) times.add(time)
    }
  }
  return [...times].sort((a, b) => a - b)
}

function metricSeries(window: TimeWindow, seed: number, baseline: number, amplitude: number): MetricPoint[] {
  const duration = durations[window]
  const random = prng(seed + duration / hour)
  return metricTimes(window).map((time, index) => ({
    t: iso(time),
    value: Math.max(0, Math.round((baseline + amplitude * (Math.sin(index / 8 + seed) + random() - 0.5)) * 100) / 100),
  }))
}

function deviceMetrics(deviceId: number, window: TimeWindow): DeviceMetrics {
  const profile = (deviceId - 1) % 6
  const cpuBaseline = [55, 39, 15, 23, 31, 47][profile]
  const inboundBaseline = [48, 32, 9, 6, 14, 25][profile] * 1_000_000
  const outboundBaseline = [35, 21, 5, 10, 8, 30][profile] * 1_000_000
  const series = (seed: number, baseline: number, amplitude: number) =>
    metricSeries(window, seed + deviceId * 100, baseline, amplitude).map(point => (
      deviceDownAt(deviceId, Date.parse(point.t)) ? { ...point, value: 0 } : point
    ))
  return {
    cpu: series(1, cpuBaseline, 9),
    memory: series(2, 40 + deviceId * 2, 4),
    throughput_in_bps: series(3, inboundBaseline, inboundBaseline * 0.2),
    throughput_out_bps: series(4, outboundBaseline, outboundBaseline * 0.2),
  }
}

export async function getNetworkMetrics(window: TimeWindow): Promise<NetworkMetrics> {
  await delay()
  const all = devices.map(device => deviceMetrics(device.id, window))
  const devicesUp = metricSeries(window, 0, 0, 0).map(point => ({
    ...point, value: devices.filter(device => !deviceDownAt(device.id, Date.parse(point.t))).length,
  }))
  const aggregate = (key: 'cpu' | 'throughput_in_bps' | 'throughput_out_bps', average: boolean) =>
    devicesUp.map((point, index) => ({
      t: point.t,
      value: Math.round(all.reduce((sum, metrics) => sum + metrics[key][index].value, 0) /
        (average ? Math.max(1, point.value) : 1) * 100) / 100,
    }))
  return {
    devices_up: devicesUp,
    cpu_avg: aggregate('cpu', true),
    throughput_in_bps: aggregate('throughput_in_bps', false),
    throughput_out_bps: aggregate('throughput_out_bps', false),
  }
}

export async function getDeviceMetrics(deviceId: number, window: TimeWindow): Promise<DeviceMetrics> {
  await delay()
  requireDevice(deviceId)
  return deviceMetrics(deviceId, window)
}
