import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import type { FormEvent } from 'react'
import { FloppyDisk, Globe, ListBullets, PencilSimple, Plus, Trash, X } from '@phosphor-icons/react'
import { api, useApi } from '../api'
import type { DnsRecord, DnsRecordType, DnsZone } from '../api'
import { useAuth } from '../auth'
import { RightPanel } from '../components/Layout'
import { Button, ConfirmDialog, DataTable, FilterBar, IconButton, PanelSection, Pill, Select, StatRow, TextInput } from '../components/ui'
import { relativeTime } from '../lib/format'
import DhcpTab from './ServicesDhcp'
import styles from './Services.module.css'

/** In-program help for every DNS field (SRS 5.3.5). Mirrors the server rules in app/dns/zones.py. */
const HELP = {
  zoneName: 'Domain the server answers for, e.g. lab.local. For reverse (PTR) lookups of 192.168.198.x use 198.168.192.in-addr.arpa.',
  zoneTtl: 'How long clients may cache answers from this zone, in seconds (30-604800). 3600 = one hour.',
  recordName: 'Name inside the zone: "r1" means r1.lab.local. Use @ for the zone itself. For PTR, the last part of the address, e.g. 11.',
  ttl: 'Optional, 30-604800 seconds. Leave empty to use the zone default.',
  value: {
    A: 'IPv4 address, e.g. 192.168.198.11.',
    AAAA: 'IPv6 address, e.g. 2001:db8::11.',
    CNAME: 'Another hostname this name is an alias for, e.g. r1.lab.local. A CNAME cannot share its name with other records, or be @.',
    PTR: 'Hostname the address points back to, e.g. r1.lab.local.',
  } satisfies Record<DnsRecordType, string>,
}

const typeOptions = (['A', 'AAAA', 'CNAME', 'PTR'] as const).map(value => ({ value, label: value }))

function parseTtl(raw: string): number | null {
  return raw.trim() === '' ? null : Number(raw)
}

type Pending = { title: string; body: string; run: () => Promise<unknown>; success: string }

const TABS = [
  { id: 'dns', label: 'DNS' },
  { id: 'dhcp', label: 'DHCP' },
] as const

/** Services screen (SRS 3.1.6): DNS and DHCP tabs. ?tab=dhcp opens DHCP directly. */
export default function Services() {
  const [params, setParams] = useSearchParams()
  const tab = params.get('tab') === 'dhcp' ? 'dhcp' : 'dns'
  return (
    <>
      <div className={styles.tabs} role="tablist" aria-label="Services">
        {TABS.map(item => (
          <button key={item.id} type="button" role="tab" aria-selected={tab === item.id}
            className={tab === item.id ? `${styles.tab} ${styles.tabActive}` : styles.tab}
            onClick={() => setParams(item.id === 'dns' ? {} : { tab: item.id })}>
            {item.label}
          </button>
        ))}
      </div>
      {tab === 'dhcp' ? <DhcpTab /> : <DnsTab />}
    </>
  )
}

/** DNS tab (R5.2). */
function DnsTab() {
  const { isAdmin } = useAuth()
  const zonesQuery = useApi(() => api.listDnsZones(), [])
  const zones = zonesQuery.data ?? []
  const [zoneId, setZoneId] = useState<number | null>(null)
  const zone = zones.find(candidate => candidate.id === zoneId) ?? null
  const recordsQuery = useApi(() => (zoneId === null ? Promise.resolve([]) : api.listDnsRecords(zoneId)), [zoneId])
  const records = recordsQuery.data ?? []
  const [recordId, setRecordId] = useState<number | null>(null)
  const record = records.find(candidate => candidate.id === recordId) ?? null

  const [addingZone, setAddingZone] = useState(false)
  const [zoneName, setZoneName] = useState('')
  const [zoneTtl, setZoneTtl] = useState('3600')
  const [editTtl, setEditTtl] = useState('')
  const [recName, setRecName] = useState('')
  const [recType, setRecType] = useState<DnsRecordType>('A')
  const [recValue, setRecValue] = useState('')
  const [recTtl, setRecTtl] = useState('')
  const [pending, setPending] = useState<Pending | null>(null)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null)

  const run = async (action: () => Promise<unknown>, success: string) => {
    setBusy(true)
    setMessage(null)
    try {
      await action()
      setMessage({ ok: true, text: success })
      zonesQuery.reload()
      recordsQuery.reload()
      return true
    } catch (reason) {
      setMessage({ ok: false, text: reason instanceof Error ? reason.message : String(reason) })
      return false
    } finally {
      setBusy(false)
    }
  }

  const selectZone = (next: DnsZone) => {
    setZoneId(next.id); setRecordId(null); setAddingZone(false); setMessage(null)
    setEditTtl(String(next.default_ttl))
  }
  const selectRecord = (next: DnsRecord) => {
    setRecordId(next.id); setMessage(null)
    setRecName(next.name); setRecValue(next.value); setRecTtl(next.ttl === null ? '' : String(next.ttl))
  }
  const resetRecordForm = () => { setRecordId(null); setRecName(''); setRecValue(''); setRecTtl(''); setRecType('A') }

  const createZone = async (event: FormEvent) => {
    event.preventDefault()
    if (await run(() => api.createDnsZone({ name: zoneName.trim(), default_ttl: Number(zoneTtl) }), `Zone '${zoneName.trim()}' created.`)) {
      setZoneName(''); setZoneTtl('3600'); setAddingZone(false)
    }
  }
  const saveRecord = async (event: FormEvent) => {
    event.preventDefault()
    if (zoneId === null) return
    const ok = record
      ? await run(() => api.updateDnsRecord(record.id, { name: recName, value: recValue, ttl: parseTtl(recTtl) }), 'Record updated.')
      : await run(() => api.createDnsRecord(zoneId, { name: recName, rtype: recType, value: recValue, ttl: parseTtl(recTtl) }), 'Record added.')
    if (ok && !record) resetRecordForm()
  }

  const error = zonesQuery.error ?? recordsQuery.error

  return (
    <>
      <FilterBar>
        <span className={styles.lead}><Globe size={14} aria-hidden="true" /> DNS: zones this server answers for</span>
        {isAdmin && <Button variant="primary" icon={Plus} onClick={() => { setAddingZone(true); setZoneId(null); setRecordId(null); setMessage(null) }}>Add zone</Button>}
      </FilterBar>
      {error && <div role="alert" className={styles.error}>{error.message}</div>}
      <div className={styles.content}>
        <h2 className={styles.heading}>Zones</h2>
        <DataTable aria-label="DNS zones" rows={zones} rowKey="id" selectedKey={zoneId ?? undefined} onRowClick={selectZone} columns={[
          { key: 'name', header: 'Zone', render: value => <span className={styles.mono}>{String(value)}</span> },
          { key: 'record_count', header: 'Records' },
          { key: 'default_ttl', header: 'Default TTL', render: value => `${value} s` },
          { key: 'updated_at', header: 'Changed', render: value => relativeTime(String(value)) },
        ]} />
        {zone && <>
          <h2 className={styles.heading}>Records in {zone.name}</h2>
          <DataTable aria-label="DNS records" rows={records} rowKey="id" selectedKey={recordId ?? undefined} onRowClick={selectRecord} columns={[
            { key: 'fqdn', header: 'Name', render: value => <span className={styles.mono}>{String(value)}</span> },
            { key: 'rtype', header: 'Type', render: value => <Pill tone="gray" size="small">{String(value)}</Pill> },
            { key: 'value', header: 'Value', render: value => <span className={styles.mono}>{String(value)}</span> },
            { key: 'ttl', header: 'TTL', render: value => (value === null ? `default (${zone.default_ttl} s)` : `${value} s`) },
          ]} />
        </>}
      </div>
      <RightPanel>
        {addingZone && isAdmin ? (
          <PanelSection title="Add zone" icon={Plus} action={<IconButton size="small" icon={X} label="Close" onClick={() => setAddingZone(false)} />}>
            <form className={styles.form} onSubmit={createZone}>
              <label className={styles.field}>Zone name<TextInput required placeholder="lab.local" value={zoneName} onChange={event => setZoneName(event.target.value)} /></label>
              <span className={styles.help}>{HELP.zoneName}</span>
              <label className={styles.field}>Default TTL (seconds)<TextInput required type="number" min={30} max={604800} value={zoneTtl} onChange={event => setZoneTtl(event.target.value)} /></label>
              <span className={styles.help}>{HELP.zoneTtl}</span>
              <Button type="submit" variant="primary" disabled={busy}>Add zone</Button>
            </form>
          </PanelSection>
        ) : zone ? (
          <>
            <PanelSection title={zone.name} icon={Globe} action={<IconButton size="small" icon={X} label="Close" onClick={() => { setZoneId(null); setRecordId(null) }} />}>
              <StatRow caption="Records" value={zone.record_count} />
              <StatRow caption="SOA serial" value={zone.serial} />
              {isAdmin ? (
                <form className={styles.form} onSubmit={async event => { event.preventDefault(); await run(() => api.updateDnsZone(zone.id, Number(editTtl)), 'Default TTL saved.') }}>
                  <label className={styles.field}>Default TTL (seconds)<TextInput required type="number" min={30} max={604800} value={editTtl} onChange={event => setEditTtl(event.target.value)} /></label>
                  <span className={styles.help}>{HELP.zoneTtl}</span>
                  <div className={styles.actions}>
                    <Button type="submit" icon={FloppyDisk} disabled={busy}>Save</Button>
                    <Button type="button" icon={Trash} disabled={busy} onClick={() => setPending({
                      title: `Delete zone '${zone.name}'?`,
                      body: `This also deletes its ${zone.record_count} record(s). Clients stop getting answers for these names immediately.`,
                      run: () => api.deleteDnsZone(zone.id), success: `Zone '${zone.name}' deleted.`,
                    })}>Delete zone</Button>
                  </div>
                </form>
              ) : <StatRow caption="Default TTL" value={`${zone.default_ttl} s`} />}
            </PanelSection>
            {isAdmin && (
              <PanelSection title={record ? `Edit ${record.rtype} record` : 'Add record'} icon={record ? PencilSimple : ListBullets}
                action={record ? <IconButton size="small" icon={X} label="Stop editing" onClick={resetRecordForm} /> : undefined}>
                <form className={styles.form} onSubmit={saveRecord}>
                  <label className={styles.field}>Name<TextInput required placeholder="r1" value={recName} onChange={event => setRecName(event.target.value)} /></label>
                  <span className={styles.help}>{HELP.recordName}</span>
                  {!record && <label className={styles.field}>Type<Select aria-label="Record type" value={recType} options={typeOptions} onChange={value => setRecType(value as DnsRecordType)} /></label>}
                  <label className={styles.field}>Value<TextInput required value={recValue} onChange={event => setRecValue(event.target.value)} /></label>
                  <span className={styles.help}>{HELP.value[record?.rtype ?? recType]}</span>
                  <label className={styles.field}>TTL (seconds)<TextInput type="number" min={30} max={604800} placeholder="zone default" value={recTtl} onChange={event => setRecTtl(event.target.value)} /></label>
                  <span className={styles.help}>{HELP.ttl}</span>
                  <div className={styles.actions}>
                    <Button type="submit" variant="primary" icon={record ? FloppyDisk : Plus} disabled={busy}>{record ? 'Save record' : 'Add record'}</Button>
                    {record && <Button type="button" icon={Trash} disabled={busy} onClick={() => setPending({
                      title: `Delete ${record.rtype} record ${record.fqdn}?`,
                      body: `Clients will get "no such name" or "no data" for ${record.fqdn} from the next query.`,
                      run: async () => { await api.deleteDnsRecord(record.id); resetRecordForm() }, success: 'Record deleted.',
                    })}>Delete</Button>}
                  </div>
                </form>
              </PanelSection>
            )}
          </>
        ) : (
          <PanelSection title="DNS" icon={Globe}>
            <p className={styles.help}>Select a zone to see its records{isAdmin ? ', or add a zone' : ''}. Changes are answered from the next query; no restart is needed.</p>
          </PanelSection>
        )}
        {message && <div role={message.ok ? 'status' : 'alert'} className={message.ok ? styles.success : styles.error}>{message.text}</div>}
      </RightPanel>
      <ConfirmDialog open={pending !== null} title={pending?.title ?? ''} confirmLabel="Delete"
        onCancel={() => setPending(null)}
        onConfirm={() => {
          if (pending) {
            const { run: action, success, title } = pending
            void run(action, success).then(ok => { if (ok && title.startsWith('Delete zone')) setZoneId(null) })
          }
          setPending(null)
        }}>
        {pending?.body}
      </ConfirmDialog>
    </>
  )
}
