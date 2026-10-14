import { useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { Check, HardDrives, ListChecks, UploadSimple, X } from '@phosphor-icons/react'
import { api, useApi } from '../api'
import type { ConfigPushResult } from '../api'
import { RightPanel } from '../components/Layout'
import { Button, Checkbox, ConfirmDialog, PanelSection, Pill, SectionHeader, StatRow, TextArea, TextInput, ToolCard } from '../components/ui'
import styles from './Push.module.css'

export default function Push() {
  const devicesQuery = useApi(() => api.listDevices(), [])
  const statusesQuery = useApi(() => api.listDeviceStatus(), [])
  const devices = devicesQuery.data ?? []
  const statuses = new Map((statusesQuery.data ?? []).map(status => [status.device_id, status.state]))
  const [selectedIds, setSelectedIds] = useState<number[]>([])
  const [snippet, setSnippet] = useState('')
  const [operator, setOperator] = useState('operator')
  const [confirming, setConfirming] = useState(false)
  const [pushing, setPushing] = useState(false)
  const pushInFlight = useRef(false)
  const [results, setResults] = useState<ConfigPushResult[] | null>(null)
  const [pushError, setPushError] = useState<string | null>(null)
  const targets = devices.filter(device => selectedIds.includes(device.id))
  const allSelected = devices.length > 0 && targets.length === devices.length
  const disabled = !targets.length || !snippet.trim() || pushing
  const error = pushError ?? devicesQuery.error?.message ?? statusesQuery.error?.message

  async function push() {
    if (disabled || pushInFlight.current) return
    pushInFlight.current = true
    setConfirming(false)
    setPushing(true)
    setPushError(null)
    setResults(null)
    try {
      setResults(await api.pushConfig({ device_ids: targets.map(device => device.id), configuration: snippet, operator }))
    } catch (reason) {
      setPushError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      pushInFlight.current = false
      setPushing(false)
    }
  }

  return (
    <>
      <div className={styles.content}>
        <SectionHeader title="Snippet">{snippet ? snippet.split('\n').length : 0} lines</SectionHeader>
        <TextArea
          aria-label="Snippet"
          className={styles.snippet}
          value={snippet}
          onChange={event => setSnippet(event.target.value)}
          placeholder={'interface GigabitEthernet0/1\n description uplink'}
          spellCheck={false}
        />
      </div>
      <RightPanel>
        <PanelSection title="Targets" icon={HardDrives} className={styles.targets}>
          <button
            type="button"
            className={styles.toggleAll}
            disabled={!devices.length}
            onClick={() => setSelectedIds(allSelected ? [] : devices.map(device => device.id))}
          >{allSelected ? 'None' : 'All'}</button>
          {devices.map(device => (
            <div key={device.id} className={styles.targetRow}>
              <Checkbox
                checked={selectedIds.includes(device.id)}
                label={device.name}
                onChange={checked => setSelectedIds(ids => checked ? [...ids, device.id] : ids.filter(id => id !== device.id))}
              />
              <Pill tone={statuses.get(device.id) === 'up' ? 'green' : 'red'} icon={statuses.get(device.id) === 'up' ? Check : X}>{statuses.get(device.id) === 'up' ? 'Up' : 'Down'}</Pill>
            </div>
          ))}
        </PanelSection>
        <PanelSection title="Push" icon={UploadSimple}>
          <ToolCard title="Operator">
            <TextInput aria-label="Operator" value={operator} onChange={event => setOperator(event.target.value)} />
          </ToolCard>
          <Button className={styles.pushButton} variant="primary" icon={UploadSimple} disabled={disabled} onClick={() => setConfirming(true)}>
            Push to {targets.length} {targets.length === 1 ? 'device' : 'devices'}
          </Button>
          {error && <div role="alert" className={styles.error}>{error}</div>}
        </PanelSection>
        {results !== null && <PanelSection title="Results" icon={ListChecks}>
          {results.map(result => {
            const name = devices.find(device => device.id === result.device_id)?.name ?? String(result.device_id)
            const succeeded = result.status === 'succeeded'
            const row = <StatRow caption={name} value={<Pill tone={succeeded ? 'green' : 'red'} icon={succeeded ? Check : X}>{succeeded ? `v${result.before_version} → v${result.after_version}` : 'Failed'}</Pill>} />
            return succeeded ? (
              <Link key={result.device_id} className={styles.resultLink} to={`/config/history?device=${result.device_id}`}>{row}</Link>
            ) : (
              <div key={result.device_id}>
                {row}
                {result.error && <div className={styles.error}>{result.error}</div>}
              </div>
            )
          })}
        </PanelSection>}
      </RightPanel>
      <ConfirmDialog open={confirming} title={`Push to ${targets.length} ${targets.length === 1 ? 'device' : 'devices'}?`} confirmLabel="Push" onConfirm={push} onCancel={() => setConfirming(false)}>
        {targets.map(device => device.name).join(', ')}
      </ConfirmDialog>
    </>
  )
}
