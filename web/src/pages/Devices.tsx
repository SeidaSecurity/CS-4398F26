import { useCallback, useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Article, ChartLine, Check, ClockCounterClockwise, Graph, HardDrives, Info, PencilSimple, Plugs, Plus, Pulse, Stack, Trash, X } from '@phosphor-icons/react'
import { api, useApi } from '../api'
import type { Device, DeviceStatus } from '../api'
import { useAuth } from '../auth'
import { RightPanel } from '../components/Layout'
import { DeviceIllustration, PortGrid, Topology, deviceKind } from '../components/devices'
import { Button, ConfirmDialog, DataTable, FilterBar, IconButton, PanelSection, Pill, Select, StatRow, TextInput } from '../components/ui'
import { formatTime, relativeTime } from '../lib/format'
import { severityPill } from '../lib/severity'
import styles from './Devices.module.css'

function statusPill(state: DeviceStatus['state'] | undefined, size: 'default' | 'small' = 'default') {
  return state && <Pill tone={state === 'up' ? 'green' : 'red'} icon={state === 'up' ? Check : X} size={size}>{state === 'up' ? 'Up' : 'Down'}</Pill>
}

export default function Devices() {
  const { isAdmin } = useAuth() // viewers see no write controls (R7.2)
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const deviceParam = searchParams.get('device')
  const selectedId = deviceParam === null ? null : Number(deviceParam)
  const [query, setQuery] = useState('')
  const [statusFilter, setStatusFilter] = useState('all')
  const [adding, setAdding] = useState(false)
  const [editing, setEditing] = useState<Device | null>(null)
  const [deleting, setDeleting] = useState<Device | null>(null)
  const [deleteError, setDeleteError] = useState<string | null>(null)
  const [name, setName] = useState('')
  const [managementIp, setManagementIp] = useState('')
  const [platform, setPlatform] = useState('cisco_ios')
  const [sshPort, setSshPort] = useState('22')
  const [submitting, setSubmitting] = useState(false)
  const [addError, setAddError] = useState<string | null>(null)

  const devicesQuery = useApi(() => api.listDevices(), [])
  const statusesQuery = useApi(() => api.listDeviceStatus(), [])
  const topologyQuery = useApi(() => api.getTopology(), [])
  const devices = devicesQuery.data ?? []
  const statusesByDevice = new Map((statusesQuery.data ?? []).map(status => [status.device_id, status]))
  const selected = adding ? undefined : devices.find(device => device.id === selectedId)
  const selectedStatus = selected ? statusesByDevice.get(selected.id) : undefined
  const selectedName = selected?.name
  const selectedDeviceId = selected?.id
  const interfacesQuery = useApi(async () => ({
    deviceId: selectedDeviceId,
    interfaces: selectedDeviceId === undefined ? [] : await api.listInterfaces(selectedDeviceId),
  }), [selectedDeviceId])
  const interfaces = selectedDeviceId !== undefined && interfacesQuery.data?.deviceId === selectedDeviceId
    ? interfacesQuery.data.interfaces : []
  const portsUp = interfaces.filter(port => port.oper_status === 'up').length
  const logsQuery = useApi(async () => ({
    source: selectedName,
    logs: selectedName ? await api.searchLogs({ source: selectedName, limit: 5 }) : [],
  }), [selectedName])
  const logs = selectedName && logsQuery.data?.source === selectedName ? logsQuery.data.logs : []

  const { reload: reloadDevices } = devicesQuery
  const { reload: reloadStatuses } = statusesQuery
  const { reload: reloadLogs } = logsQuery
  const { reload: reloadTopology } = topologyQuery
  const { reload: reloadInterfaces } = interfacesQuery
  const reload = useCallback(() => {
    reloadDevices()
    reloadStatuses()
    reloadLogs()
    reloadTopology()
    reloadInterfaces()
  }, [reloadDevices, reloadStatuses, reloadLogs, reloadTopology, reloadInterfaces])

  useEffect(() => {
    const interval = setInterval(reload, 60_000)
    return () => clearInterval(interval)
  }, [reload])

  function setSelectedId(id: number | null) {
    setEditing(null)
    setDeleteError(null)
    setSearchParams(params => {
      const next = new URLSearchParams(params)
      if (id === null) next.delete('device')
      else next.set('device', String(id))
      return next
    })
  }

  function openAdd() {
    setSelectedId(null)
    setName('')
    setManagementIp('')
    setPlatform('cisco_ios')
    setSshPort('22')
    setAddError(null)
    setAdding(true)
  }

  function openEdit() {
    if (!selected) return
    setName(selected.name)
    setManagementIp(selected.management_ip)
    setPlatform(selected.platform)
    setSshPort(String(selected.ssh_port))
    setAddError(null)
    setEditing(selected)
  }

  async function saveDevice(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (submitting) return
    setSubmitting(true)
    setAddError(null)
    try {
      const payload = {
        name: name.trim(),
        management_ip: managementIp.trim(),
        platform: platform.trim() || 'cisco_ios',
        ssh_port: Number(sshPort),
      }
      const device = editing
        ? await api.updateDevice(editing.id, payload)
        : await api.createDevice(payload)
      reload()
      setAdding(false)
      setSelectedId(device.id)
    } catch (reason) {
      setAddError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setSubmitting(false)
    }
  }

  async function removeDevice() {
    if (!deleting || submitting) return
    setSubmitting(true)
    setDeleteError(null)
    setDeleting(null)
    try {
      await api.deleteDevice(deleting.id)
      setSelectedId(null)
      reload()
    } catch (reason) {
      setDeleteError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setSubmitting(false)
    }
  }

  const search = query.trim().toLowerCase()
  const rows = devices.map(device => ({
    ...device,
    status: statusesByDevice.get(device.id)?.state,
    last_poll_at: statusesByDevice.get(device.id)?.last_poll_at,
  })).filter(device => (
    (!search || device.name.toLowerCase().includes(search) || device.management_ip.toLowerCase().includes(search))
    && (statusFilter === 'all' || device.status === statusFilter)
  )).sort((a, b) => a.name.localeCompare(b.name))
  const up = devices.filter(device => statusesByDevice.get(device.id)?.state === 'up').length
  const down = devices.filter(device => statusesByDevice.get(device.id)?.state === 'down').length
  const error = devicesQuery.error ?? statusesQuery.error ?? topologyQuery.error
    ?? (selected ? interfacesQuery.error ?? logsQuery.error : null)

  return (
    <>
      <FilterBar>
        <TextInput aria-label="Search" placeholder="Search" style={{ width: 180 }} value={query} onChange={event => setQuery(event.target.value)} />
        <Select icon={Pulse} aria-label="Status" value={statusFilter} onChange={setStatusFilter} options={[
          { value: 'all', label: 'All' },
          { value: 'up', label: 'Up' },
          { value: 'down', label: 'Down' },
        ]} />
        {isAdmin && <Button variant="primary" icon={Plus} onClick={openAdd} disabled={submitting}>Add device</Button>}
      </FilterBar>
      {error && <div role="alert" className={styles.error}>{error.message}</div>}
      <div className={styles.content}>
        <DataTable aria-label="Devices" rows={rows} rowKey="id" selectedKey={selectedId ?? undefined} onRowClick={device => { setAdding(false); setSelectedId(device.id) }} columns={[
          { key: 'name', header: 'Name', render: (_, device) => <span className={styles.name}><span aria-hidden="true" className={styles.dot} style={{ background: device.status === 'up' ? 'var(--green-600)' : device.status === 'down' ? 'var(--red-600)' : undefined }} />{device.name}</span> },
          { key: 'management_ip', header: 'Management IP', render: (_, device) => <span className={styles.mono}>{device.management_ip}</span> },
          { key: 'platform', header: 'Platform', render: (_, device) => <span className={styles.mono}>{device.platform}</span> },
          { key: 'ssh_port', header: 'SSH port' },
          { key: 'status', header: 'Status', render: (_, device) => statusPill(device.status, 'small') },
          { key: 'last_poll_at', header: 'Last poll', render: (_, device) => device.last_poll_at && relativeTime(device.last_poll_at) },
        ]} />
      </div>
      <RightPanel>
        {adding || editing ? (
          <PanelSection title={editing ? 'Edit device' : 'Add device'} icon={editing ? PencilSimple : Plus} action={<IconButton size="small" icon={X} label="Close" onClick={() => { setAdding(false); setEditing(null) }} disabled={submitting} />}>
            <form className={styles.form} onSubmit={saveDevice}>
              <label className={styles.field}>Name<TextInput required value={name} onChange={event => setName(event.target.value)} disabled={submitting} /></label>
              <label className={styles.field}>Management IP<TextInput required value={managementIp} onChange={event => setManagementIp(event.target.value)} disabled={submitting} /></label>
              <label className={styles.field}>Platform<TextInput value={platform} onChange={event => setPlatform(event.target.value)} disabled={submitting} /></label>
              <label className={styles.field}>SSH port<TextInput type="number" min={1} max={65535} required value={sshPort} onChange={event => setSshPort(event.target.value)} disabled={submitting} /></label>
              {addError && <div role="alert" className={styles.addError}>{addError}</div>}
              <Button type="submit" variant="primary" disabled={submitting}>{editing ? 'Save' : 'Add'}</Button>
            </form>
          </PanelSection>
        ) : selected ? (
          <>
            <PanelSection title={selected.name} icon={HardDrives} action={<IconButton size="small" icon={X} label="Close" onClick={() => setSelectedId(null)} />}>
              <div className={styles.illustration}>
                <DeviceIllustration width={200} kind={deviceKind(selected.name, selected.platform)} state={selectedStatus?.state} />
              </div>
              <StatRow caption="Status" value={statusPill(selectedStatus?.state)} />
              <StatRow caption="Management IP" value={<span className={styles.mono}>{selected.management_ip}</span>} />
              <StatRow caption="Platform" value={<span className={styles.mono}>{selected.platform}</span>} />
              <StatRow caption="SSH port" value={selected.ssh_port} />
              <StatRow caption="Last poll" value={selectedStatus && relativeTime(selectedStatus.last_poll_at)} />
              <StatRow caption="Added" value={formatTime(selected.created_at)} />
              {isAdmin && <div className={styles.actions}>
                <Button icon={PencilSimple} onClick={openEdit} disabled={submitting}>Edit</Button>
                <Button icon={Trash} onClick={() => { setDeleteError(null); setDeleting(selected) }} disabled={submitting}>Delete</Button>
              </div>}
              {deleteError && <div role="alert" className={styles.addError}>{deleteError}</div>}
            </PanelSection>
            <PanelSection title="Ports" icon={Plugs} action={<span className={styles.portCount}>{portsUp}/{interfaces.length} up</span>}>
              <PortGrid ports={interfaces.map(port => ({ index: port.index, name: port.name, up: port.oper_status === 'up' }))} />
              <div className={styles.actions}>
                <Button icon={ChartLine} onClick={() => navigate(`/?device=${selected.id}`)}>Metrics</Button>
                <Button icon={ClockCounterClockwise} onClick={() => navigate(`/config/history?device=${selected.id}`)}>Config history</Button>
              </div>
            </PanelSection>
            {logs.length > 0 && <PanelSection title="Recent logs" icon={Article}>
              {logs.map(log => (
                <div key={log.id} className={styles.log}>
                  {severityPill(log.severity)}
                  <span className={styles.logBody} title={log.body}>{log.body}</span>
                  <span className={styles.logTime}>{relativeTime(log.timestamp)}</span>
                </div>
              ))}
            </PanelSection>}
          </>
        ) : (
          <>
            <PanelSection title="Topology" icon={Graph}>
              <Topology
                width={247}
                nodes={devices.map(device => ({
                  id: device.id,
                  name: device.name,
                  kind: deviceKind(device.name, device.platform),
                  state: statusesByDevice.get(device.id)?.state ?? 'up',
                }))}
                links={(topologyQuery.data ?? []).map(link => [link.a, link.b])}
                onSelect={setSelectedId}
              />
            </PanelSection>
            <PanelSection title="Stats" icon={Info}>
              <StatRow caption="Devices" value={<Pill tone="gray" icon={HardDrives}>{devices.length}</Pill>} />
              <StatRow caption="Up" value={<Pill tone="green" icon={Check}>{up}</Pill>} />
              <StatRow caption="Down" value={<Pill tone={down ? 'red' : 'green'} icon={down ? X : Check}>{down}</Pill>} />
              <StatRow caption="Platforms" value={<Pill tone="gray" icon={Stack}>{new Set(devices.map(device => device.platform)).size}</Pill>} />
            </PanelSection>
          </>
        )}
      </RightPanel>
      <ConfirmDialog open={deleting !== null} title={`Delete ${deleting?.name ?? 'device'}?`} confirmLabel="Delete" onConfirm={removeDevice} onCancel={() => setDeleting(null)}>
        This will permanently delete the device.
      </ConfirmDialog>
    </>
  )
}
