import type {
  ConnectionTestRequest,
  ConnectionTestResult,
  Alert, AuditRecord, ConfigPushRequest, ConfigPushResult, ConfigVersion,
  ConfigTemplate, ConfigTemplateCreate, ConfigTemplateRenderRequest,
  ConfigVersionDetail, Device, DeviceCreate, DeviceMetrics, DeviceStatus,
  Interface, LogQuery, LogRecord, MetricPoint, NetworkMetrics, TimeWindow, TopologyLink,
  CurrentUser, UserAccount, UserCreate, UserUpdate,
  DnsRecord, DnsRecordCreate, DnsRecordUpdate, DnsZone, DnsZoneCreate,
  DhcpLease, DhcpPool, DhcpPoolCreate, DhcpPoolUpdate, DhcpReservation, DhcpReservationCreate,
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
  has_credentials: index < 3,
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

// Mock R1.3: addresses ending in .99 are unreachable; the password "wrong" is refused.
export async function testConnection(form: ConnectionTestRequest): Promise<ConnectionTestResult> {
  await delay()
  const address = `${form.management_ip}:${form.ssh_port ?? 22}`
  const reach = { stage: 'reachability' as const, ok: true, message: `${address} is reachable.` }
  if (form.management_ip.trim().endsWith('.99')) {
    const message = `Nothing answered on ${address}. Check the management IP and SSH port, and that the device is powered on with SSH enabled.`
    return { ok: false, failed_stage: 'reachability', message, checks: [{ ...reach, ok: false, message }] }
  }
  if (!(form.username && form.password)) {
    return { ok: true, failed_stage: null, message: `${address} is reachable. Login not tested: no username and password entered.`, checks: [reach] }
  }
  if (form.password === 'wrong') {
    const message = 'The device refused the login. Check the username and password.'
    return { ok: false, failed_stage: 'login', message, checks: [reach, { stage: 'login', ok: false, message }] }
  }
  return { ok: true, failed_stage: null, message: 'Reachable and the login succeeded.', checks: [reach, { stage: 'login', ok: true, message: `Logged in as ${form.username}.` }] }
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
    has_credentials: Boolean(payload.username && payload.password),
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
  Object.assign(device, updated, { has_credentials: device.has_credentials || Boolean(patch.password) })
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

// The real server takes the operator from the session; mock mode uses the mock signed-in user.
function mockOperator(): string {
  return mockSession?.username ?? 'admin'
}

export async function retrieveConfig(deviceId: number): Promise<ConfigVersion> {
  await delay()
  const operator = mockOperator()
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
  const operator = mockOperator()
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

export async function restoreConfig(deviceId: number, version: number): Promise<ConfigPushResult> {
  await delay()
  const operator = mockOperator()
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

// --- Authentication and accounts (mock) -------------------------------------------------------
// Two built-in accounts; any password works in mock mode (the Login screen says so).

const mockUsers: UserAccount[] = [
  { id: 1, username: 'admin', role: 'admin', disabled: false, created_at: iso(Date.now() - 86_400_000) },
  { id: 2, username: 'viewer', role: 'viewer', disabled: false, created_at: iso(Date.now() - 86_400_000) },
]
let mockSession: CurrentUser | null = null
const loginFailed = 'Invalid username or password.'

function asCurrentUser({ id, username, role, created_at }: UserAccount): CurrentUser {
  return { id, username, role, created_at }
}

export async function login(username: string, password: string): Promise<CurrentUser> {
  await delay()
  const user = mockUsers.find(candidate => candidate.username.toLowerCase() === username.toLowerCase())
  if (!user || user.disabled || !password) {
    recordAudit(username, 'auth.login', 'failed', null, 'Invalid credentials')
    throw new Error(loginFailed)
  }
  mockSession = asCurrentUser(user)
  recordAudit(user.username, 'auth.login', 'succeeded', null, '')
  return copy(mockSession)
}

export async function logout(): Promise<void> {
  await delay()
  if (mockSession) recordAudit(mockSession.username, 'auth.logout', 'succeeded', null, '')
  mockSession = null
}

export async function me(): Promise<CurrentUser> {
  await delay()
  if (!mockSession) throw new Error('You are not logged in. Log in and try again.')
  return copy(mockSession)
}

export async function listUsers(): Promise<UserAccount[]> {
  await delay()
  return copy([...mockUsers].sort((a, b) => a.username.localeCompare(b.username)))
}

export async function createUser(payload: UserCreate): Promise<UserAccount> {
  await delay()
  if (payload.password.length < 8 || payload.password.length > 64) {
    throw new Error('Password must be 8-64 characters long; a passphrase of several words works well.')
  }
  if (mockUsers.some(user => user.username.toLowerCase() === payload.username.toLowerCase())) {
    throw new Error(`A user named '${payload.username}' already exists.`)
  }
  const user: UserAccount = {
    id: Math.max(...mockUsers.map(u => u.id)) + 1, username: payload.username, role: payload.role,
    disabled: false, created_at: iso(Date.now()),
  }
  mockUsers.push(user)
  recordAudit(mockOperator(), 'user.create', 'succeeded', null, `Created ${user.role} '${user.username}'`)
  return copy(user)
}

export async function updateUser(userId: number, patch: UserUpdate): Promise<UserAccount> {
  await delay()
  const user = mockUsers.find(candidate => candidate.id === userId)
  if (!user) throw new Error('User not found. Refresh the list.')
  const activeAdmins = mockUsers.filter(u => u.role === 'admin' && !u.disabled).length
  const losesAdmin = user.role === 'admin' && !user.disabled
    && ((patch.role !== undefined && patch.role !== 'admin') || patch.disabled === true)
  if (losesAdmin && activeAdmins <= 1) {
    throw new Error(`'${user.username}' is the last active administrator. Make another user an admin first.`)
  }
  if (patch.role !== undefined) user.role = patch.role
  if (patch.disabled !== undefined) user.disabled = patch.disabled
  recordAudit(mockOperator(), 'user.update', 'succeeded', null, `User '${user.username}' updated`)
  return copy(user)
}

// --- DNS (mock) -------------------------------------------------------------------------------
// Light validation only: the real rules (and RFC checks) live on the server (app/dns/zones.py).

type MockZone = Omit<DnsZone, 'record_count'>
const dnsZones: MockZone[] = [
  { id: 1, name: 'lab.local', default_ttl: 3600, serial: 3, created_at: iso(Date.now() - 86_400_000), updated_at: iso(Date.now() - 3_600_000) },
]
const dnsRecords: DnsRecord[] = [
  { id: 1, zone_id: 1, name: 'r1', fqdn: 'r1.lab.local', rtype: 'A', value: '192.168.198.11', ttl: null, created_at: iso(Date.now() - 80_000_000) },
  { id: 2, zone_id: 1, name: 'www', fqdn: 'www.lab.local', rtype: 'CNAME', value: 'r1.lab.local', ttl: 300, created_at: iso(Date.now() - 70_000_000) },
]
const ipv4 = /^(25[0-5]|2[0-4]\d|1?\d?\d)(\.(25[0-5]|2[0-4]\d|1?\d?\d)){3}$/

function requireZone(zoneId: number): MockZone {
  const zone = dnsZones.find(candidate => candidate.id === zoneId)
  if (!zone) throw new Error('Zone not found. Refresh the zone list.')
  return zone
}

function withCount(zone: MockZone): DnsZone {
  return { ...zone, record_count: dnsRecords.filter(record => record.zone_id === zone.id).length }
}

function touchZone(zone: MockZone) {
  zone.serial += 1
  zone.updated_at = iso(Date.now())
}

export async function listDnsZones(): Promise<DnsZone[]> {
  await delay()
  return copy([...dnsZones].sort((a, b) => a.name.localeCompare(b.name)).map(withCount))
}

export async function createDnsZone(payload: DnsZoneCreate): Promise<DnsZone> {
  await delay()
  const name = payload.name.trim().toLowerCase().replace(/\.$/, '')
  if (!/^[a-z0-9-]+(\.[a-z0-9-]+)*$/.test(name)) throw new Error(`Zone name '${payload.name}' is invalid.`)
  if (dnsZones.some(zone => zone.name === name)) throw new Error(`Zone '${name}' already exists.`)
  const zone: MockZone = {
    id: Math.max(0, ...dnsZones.map(z => z.id)) + 1, name, default_ttl: payload.default_ttl ?? 3600,
    serial: 1, created_at: iso(Date.now()), updated_at: iso(Date.now()),
  }
  dnsZones.push(zone)
  recordAudit(mockOperator(), 'dns.zone.create', 'succeeded', null, `Zone '${name}'`)
  return copy(withCount(zone))
}

export async function updateDnsZone(zoneId: number, defaultTtl: number): Promise<DnsZone> {
  await delay()
  const zone = requireZone(zoneId)
  zone.default_ttl = defaultTtl
  touchZone(zone)
  return copy(withCount(zone))
}

export async function deleteDnsZone(zoneId: number): Promise<void> {
  await delay()
  const zone = requireZone(zoneId)
  dnsZones.splice(dnsZones.indexOf(zone), 1)
  for (let index = dnsRecords.length - 1; index >= 0; index--) {
    if (dnsRecords[index].zone_id === zoneId) dnsRecords.splice(index, 1)
  }
}

export async function listDnsRecords(zoneId: number): Promise<DnsRecord[]> {
  await delay()
  requireZone(zoneId)
  return copy(dnsRecords.filter(record => record.zone_id === zoneId))
}

export async function createDnsRecord(zoneId: number, payload: DnsRecordCreate): Promise<DnsRecord> {
  await delay()
  const zone = requireZone(zoneId)
  if (payload.rtype === 'A' && !ipv4.test(payload.value.trim())) {
    throw new Error("An A record's value must be an IPv4 address like 192.168.198.11.")
  }
  const name = payload.name.trim().toLowerCase()
  const record: DnsRecord = {
    id: Math.max(0, ...dnsRecords.map(r => r.id)) + 1, zone_id: zoneId, name,
    fqdn: name === '@' ? zone.name : `${name}.${zone.name}`, rtype: payload.rtype,
    value: payload.value.trim(), ttl: payload.ttl ?? null, created_at: iso(Date.now()),
  }
  dnsRecords.push(record)
  touchZone(zone)
  return copy(record)
}

export async function updateDnsRecord(recordId: number, patch: DnsRecordUpdate): Promise<DnsRecord> {
  await delay()
  const record = dnsRecords.find(candidate => candidate.id === recordId)
  if (!record) throw new Error('Record not found. Refresh the record list.')
  const zone = requireZone(record.zone_id)
  if (patch.name !== undefined) {
    record.name = patch.name.trim().toLowerCase()
    record.fqdn = record.name === '@' ? zone.name : `${record.name}.${zone.name}`
  }
  if (patch.value !== undefined) record.value = patch.value.trim()
  if (patch.ttl !== undefined) record.ttl = patch.ttl
  touchZone(zone)
  return copy(record)
}

export async function deleteDnsRecord(recordId: number): Promise<void> {
  await delay()
  const index = dnsRecords.findIndex(candidate => candidate.id === recordId)
  if (index < 0) throw new Error('Record not found. Refresh the record list.')
  touchZone(requireZone(dnsRecords[index].zone_id))
  dnsRecords.splice(index, 1)
}

// --- DHCP (mock) ------------------------------------------------------------------------------
// Light validation only: the real rules live on the server (app/dhcp/pools.py).

type MockPool = Omit<DhcpPool, 'reservation_count' | 'active_lease_count'>
const dhcpPools: MockPool[] = [
  {
    id: 1, name: 'lab-clients', subnet: '192.168.50.0/24', range_start: '192.168.50.100',
    range_end: '192.168.50.199', gateway: '192.168.50.1', dns_servers: ['192.168.50.1'],
    domain: 'lab.local', lease_seconds: 3600, created_at: iso(Date.now() - 86_400_000),
    updated_at: iso(Date.now() - 3_600_000),
  },
]
const dhcpReservations: DhcpReservation[] = [
  { id: 1, pool_id: 1, mac: 'aa:bb:cc:dd:ee:07', ip: '192.168.50.10', hostname: 'printer', created_at: iso(Date.now() - 80_000_000) },
]
const dhcpLeases: DhcpLease[] = [
  { id: 1, pool_id: 1, pool_name: 'lab-clients', mac: 'aa:bb:cc:dd:ee:01', ip: '192.168.50.100', hostname: 'alpine-1', state: 'bound', expires_at: iso(Date.now() + 3_000_000) },
  { id: 2, pool_id: 1, pool_name: 'lab-clients', mac: 'aa:bb:cc:dd:ee:02', ip: '192.168.50.101', hostname: null, state: 'offered', expires_at: iso(Date.now() + 45_000) },
]

function requirePool(poolId: number): MockPool {
  const pool = dhcpPools.find(candidate => candidate.id === poolId)
  if (!pool) throw new Error('Pool not found. Refresh the pool list.')
  return pool
}

function activeLeases(): DhcpLease[] {
  return dhcpLeases.filter(lease => new Date(lease.expires_at).getTime() > Date.now())
}

function withPoolCounts(pool: MockPool): DhcpPool {
  return {
    ...pool,
    reservation_count: dhcpReservations.filter(r => r.pool_id === pool.id).length,
    active_lease_count: activeLeases().filter(l => l.pool_id === pool.id).length,
  }
}

export async function listDhcpPools(): Promise<DhcpPool[]> {
  await delay()
  return copy([...dhcpPools].sort((a, b) => a.name.localeCompare(b.name)).map(withPoolCounts))
}

export async function createDhcpPool(payload: DhcpPoolCreate): Promise<DhcpPool> {
  await delay()
  if (dhcpPools.some(pool => pool.name.toLowerCase() === payload.name.toLowerCase())) {
    throw new Error(`A pool with the name '${payload.name}' already exists.`)
  }
  if (payload.lease_seconds < 60 || payload.lease_seconds > 604800) throw new Error('Lease time must be 60-604800 seconds.')
  const pool: MockPool = {
    ...payload, id: Math.max(0, ...dhcpPools.map(p => p.id)) + 1,
    created_at: iso(Date.now()), updated_at: iso(Date.now()),
  }
  dhcpPools.push(pool)
  recordAudit(mockOperator(), 'dhcp.pool.create', 'succeeded', null, `Pool '${pool.name}'`)
  return copy(withPoolCounts(pool))
}

export async function updateDhcpPool(poolId: number, patch: DhcpPoolUpdate): Promise<DhcpPool> {
  await delay()
  const pool = requirePool(poolId)
  Object.assign(pool, patch, { updated_at: iso(Date.now()) })
  return copy(withPoolCounts(pool))
}

export async function deleteDhcpPool(poolId: number): Promise<void> {
  await delay()
  const pool = requirePool(poolId)
  dhcpPools.splice(dhcpPools.indexOf(pool), 1)
  for (const list of [dhcpReservations, dhcpLeases] as { pool_id: number }[][]) {
    for (let index = list.length - 1; index >= 0; index--) if (list[index].pool_id === poolId) list.splice(index, 1)
  }
}

export async function listDhcpReservations(poolId: number): Promise<DhcpReservation[]> {
  await delay()
  requirePool(poolId)
  return copy(dhcpReservations.filter(r => r.pool_id === poolId))
}

export async function createDhcpReservation(poolId: number, payload: DhcpReservationCreate): Promise<DhcpReservation> {
  await delay()
  requirePool(poolId)
  const mac = payload.mac.trim().toLowerCase().replace(/-/g, ':')
  if (!/^([0-9a-f]{2}:){5}[0-9a-f]{2}$/.test(mac)) throw new Error(`MAC address '${payload.mac}' is invalid. Use a form like aa:bb:cc:dd:ee:ff.`)
  if (dhcpReservations.some(r => r.pool_id === poolId && r.mac === mac)) throw new Error(`MAC ${mac} already has a reservation.`)
  const reservation: DhcpReservation = {
    id: Math.max(0, ...dhcpReservations.map(r => r.id)) + 1, pool_id: poolId, mac,
    ip: payload.ip.trim(), hostname: payload.hostname || null, created_at: iso(Date.now()),
  }
  dhcpReservations.push(reservation)
  return copy(reservation)
}

export async function deleteDhcpReservation(reservationId: number): Promise<void> {
  await delay()
  const index = dhcpReservations.findIndex(r => r.id === reservationId)
  if (index < 0) throw new Error('Reservation not found. Refresh the list.')
  dhcpReservations.splice(index, 1)
}

export async function listDhcpLeases(poolId?: number): Promise<DhcpLease[]> {
  await delay()
  return copy(activeLeases().filter(lease => poolId === undefined || lease.pool_id === poolId))
}

export async function releaseDhcpLease(leaseId: number): Promise<void> {
  await delay()
  const index = dhcpLeases.findIndex(l => l.id === leaseId)
  if (index < 0) throw new Error('Lease not found or already expired. Refresh the lease list.')
  dhcpLeases.splice(index, 1)
}
