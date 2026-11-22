import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { ArrowCounterClockwise, FloppyDisk, IdentificationCard, Info, Network, Plus, Trash, X } from '@phosphor-icons/react'
import { api, useApi } from '../api'
import type { DhcpPool, DhcpPoolCreate } from '../api'
import { useAuth } from '../auth'
import { RightPanel } from '../components/Layout'
import { Button, ConfirmDialog, DataTable, FilterBar, IconButton, PanelSection, Pill, StatRow, TextInput } from '../components/ui'
import { formatTime, relativeTime } from '../lib/format'
import styles from './Services.module.css'

/** In-program help for every DHCP field (SRS 5.3.5). Mirrors the server rules in app/dhcp/pools.py. */
const HELP = {
  name: 'A label for this pool, e.g. lab-clients.',
  subnet: 'The network the pool serves, as address/prefix with the host part zero, e.g. 192.168.50.0/24. Must contain this server\'s DHCP_SERVER_IP and must not overlap another pool.',
  range: 'First and last address handed out, inside the subnet, e.g. 192.168.50.100 to 192.168.50.199. Not the network (.0) or broadcast (.255) address.',
  gateway: 'Default router given to clients, inside the subnet but outside the range, e.g. 192.168.50.1.',
  dns: 'Up to 3 DNS server addresses, comma-separated, e.g. 192.168.50.1 (this app\'s DNS service).',
  domain: 'Domain name given to clients, e.g. lab.local.',
  lease: 'How long a client may keep its address, in seconds (60-604800). 3600 = one hour; short leases make expiry easy to demonstrate.',
  mac: 'The client\'s hardware address: aa:bb:cc:dd:ee:ff, aa-bb-cc-dd-ee-ff or Cisco aabb.ccdd.eeff all work.',
  reservedIp: 'The fixed address this device always gets. Must be inside the subnet; it may be outside the dynamic range. Not the gateway.',
  hostname: 'Optional name recorded for the device, e.g. printer.',
}

type PoolForm = Record<'name' | 'subnet' | 'range_start' | 'range_end' | 'gateway' | 'dns' | 'domain' | 'lease', string>
const EMPTY_POOL: PoolForm = {
  name: '', subnet: '192.168.50.0/24', range_start: '192.168.50.100', range_end: '192.168.50.199',
  gateway: '192.168.50.1', dns: '192.168.50.1', domain: 'lab.local', lease: '3600',
}

function toForm(pool: DhcpPool): PoolForm {
  return {
    name: pool.name, subnet: pool.subnet, range_start: pool.range_start, range_end: pool.range_end,
    gateway: pool.gateway, dns: pool.dns_servers.join(', '), domain: pool.domain, lease: String(pool.lease_seconds),
  }
}

function toPayload(form: PoolForm): DhcpPoolCreate {
  return {
    name: form.name.trim(), subnet: form.subnet.trim(), range_start: form.range_start.trim(),
    range_end: form.range_end.trim(), gateway: form.gateway.trim(),
    dns_servers: form.dns.split(',').map(item => item.trim()).filter(Boolean),
    domain: form.domain.trim(), lease_seconds: Number(form.lease),
  }
}

type Pending = { title: string; body: string; label: string; run: () => Promise<unknown>; success: string; after?: () => void }

/** Services screen, DHCP tab (SRS 3.1.6; R6.2 pools, R6.3 reservations, R6.4 active leases). */
export default function DhcpTab() {
  const { isAdmin } = useAuth()
  const poolsQuery = useApi(() => api.listDhcpPools(), [])
  const pools = poolsQuery.data ?? []
  const [poolId, setPoolId] = useState<number | null>(null)
  const pool = pools.find(candidate => candidate.id === poolId) ?? null
  const reservationsQuery = useApi(() => (poolId === null ? Promise.resolve([]) : api.listDhcpReservations(poolId)), [poolId])
  const reservations = reservationsQuery.data ?? []
  const leasesQuery = useApi(() => api.listDhcpLeases(poolId ?? undefined), [poolId])
  const leases = leasesQuery.data ?? []
  const [reservationId, setReservationId] = useState<number | null>(null)
  const reservation = reservations.find(candidate => candidate.id === reservationId) ?? null
  const [leaseId, setLeaseId] = useState<number | null>(null)
  const lease = leases.find(candidate => candidate.id === leaseId) ?? null

  const [adding, setAdding] = useState(false)
  const [form, setForm] = useState<PoolForm>(EMPTY_POOL)
  const [mac, setMac] = useState('')
  const [reservedIp, setReservedIp] = useState('')
  const [hostname, setHostname] = useState('')
  const [pending, setPending] = useState<Pending | null>(null)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null)

  // R6.4: the leases table follows clients live (offered -> bound, renewals, expiry).
  useEffect(() => {
    const timer = setInterval(() => { leasesQuery.reload(); poolsQuery.reload() }, 10_000)
    return () => clearInterval(timer)
  }, [leasesQuery.reload, poolsQuery.reload])

  const reloadAll = () => { poolsQuery.reload(); reservationsQuery.reload(); leasesQuery.reload() }
  const run = async (action: () => Promise<unknown>, success: string) => {
    setBusy(true)
    setMessage(null)
    try {
      await action()
      setMessage({ ok: true, text: success })
      reloadAll()
      return true
    } catch (reason) {
      setMessage({ ok: false, text: reason instanceof Error ? reason.message : String(reason) })
      return false
    } finally {
      setBusy(false)
    }
  }

  const selectPool = (next: DhcpPool) => {
    setPoolId(next.id); setReservationId(null); setLeaseId(null); setAdding(false); setMessage(null); setForm(toForm(next))
  }
  const field = (key: keyof PoolForm) => ({ value: form[key], onChange: (event: { target: { value: string } }) => setForm({ ...form, [key]: event.target.value }) })
  const firstPool = pools.length === 0

  const createPool = async (event: FormEvent) => {
    event.preventDefault()
    const ok = await run(() => api.createDhcpPool(toPayload(form)),
      firstPool ? `Pool '${form.name.trim()}' created. Restart the app so DHCP starts serving it.` : `Pool '${form.name.trim()}' created.`)
    if (ok) { setAdding(false); setForm(EMPTY_POOL) }
  }
  const savePool = async (event: FormEvent) => {
    event.preventDefault()
    if (pool) await run(() => api.updateDhcpPool(pool.id, toPayload(form)), 'Pool saved.')
  }
  const addReservation = async (event: FormEvent) => {
    event.preventDefault()
    if (!pool) return
    const ok = await run(() => api.createDhcpReservation(pool.id, { mac, ip: reservedIp, hostname: hostname || null }), `Reservation added for ${mac}.`)
    if (ok) { setMac(''); setReservedIp(''); setHostname('') }
  }

  const poolFields = (
    <>
      <label className={styles.field}>Name<TextInput required value={form.name} onChange={field('name').onChange} /></label>
      <span className={styles.help}>{HELP.name}</span>
      <label className={styles.field}>Subnet<TextInput required {...field('subnet')} /></label>
      <span className={styles.help}>{HELP.subnet}</span>
      <label className={styles.field}>Range start<TextInput required {...field('range_start')} /></label>
      <label className={styles.field}>Range end<TextInput required {...field('range_end')} /></label>
      <span className={styles.help}>{HELP.range}</span>
      <label className={styles.field}>Gateway<TextInput required {...field('gateway')} /></label>
      <span className={styles.help}>{HELP.gateway}</span>
      <label className={styles.field}>DNS servers<TextInput required {...field('dns')} /></label>
      <span className={styles.help}>{HELP.dns}</span>
      <label className={styles.field}>Domain<TextInput required {...field('domain')} /></label>
      <span className={styles.help}>{HELP.domain}</span>
      <label className={styles.field}>Lease time (seconds)<TextInput required type="number" min={60} max={604800} {...field('lease')} /></label>
      <span className={styles.help}>{HELP.lease}</span>
    </>
  )

  const error = poolsQuery.error ?? reservationsQuery.error ?? leasesQuery.error

  return (
    <>
      <FilterBar>
        <span className={styles.lead}><Network size={14} aria-hidden="true" /> DHCP: address pools this server hands out</span>
        {isAdmin && <Button variant="primary" icon={Plus} onClick={() => { setAdding(true); setPoolId(null); setForm(EMPTY_POOL); setMessage(null) }}>Add pool</Button>}
      </FilterBar>
      {error && <div role="alert" className={styles.error}>{error.message}</div>}
      <div className={styles.content}>
        <p className={styles.notice}><Info size={14} aria-hidden="true" /> DHCP answers only on the network of a pool that contains this server&apos;s DHCP_SERVER_IP. After creating the <b>first</b> pool, restart the app so DHCP starts.</p>
        <h2 className={styles.heading}>Pools</h2>
        <DataTable aria-label="DHCP pools" rows={pools} rowKey="id" selectedKey={poolId ?? undefined} onRowClick={selectPool} columns={[
          { key: 'name', header: 'Pool' },
          { key: 'subnet', header: 'Subnet', render: value => <span className={styles.mono}>{String(value)}</span> },
          { key: 'range_start', header: 'Range', render: (_, row) => <span className={styles.mono}>{row.range_start} - {row.range_end}</span> },
          { key: 'gateway', header: 'Gateway', render: value => <span className={styles.mono}>{String(value)}</span> },
          { key: 'lease_seconds', header: 'Lease', render: value => `${value} s` },
          { key: 'active_lease_count', header: 'Active leases' },
          { key: 'reservation_count', header: 'Reservations' },
        ]} />
        {pool && <>
          <h2 className={styles.heading}>Reservations in {pool.name}</h2>
          <DataTable aria-label="DHCP reservations" rows={reservations} rowKey="id" selectedKey={reservationId ?? undefined}
            onRowClick={row => { setReservationId(row.id); setLeaseId(null); setMessage(null) }} columns={[
              { key: 'mac', header: 'MAC', render: value => <span className={styles.mono}>{String(value)}</span> },
              { key: 'ip', header: 'Reserved IP', render: value => <span className={styles.mono}>{String(value)}</span> },
              { key: 'hostname', header: 'Hostname', render: value => (value ? String(value) : '-') },
            ]} />
        </>}
        <h2 className={styles.heading}>Active leases{pool ? ` in ${pool.name}` : ' (all pools)'} <span className={styles.lead}>refreshes every 10 s</span></h2>
        <DataTable aria-label="DHCP leases" rows={leases} rowKey="id" selectedKey={leaseId ?? undefined}
          onRowClick={row => { setLeaseId(row.id); setReservationId(null); setMessage(null) }} columns={[
            { key: 'mac', header: 'MAC', render: value => <span className={styles.mono}>{String(value)}</span> },
            { key: 'ip', header: 'IP address', render: value => <span className={styles.mono}>{String(value)}</span> },
            { key: 'hostname', header: 'Hostname', render: value => (value ? String(value) : '-') },
            { key: 'state', header: 'State', render: value => <Pill tone={value === 'bound' ? 'green' : 'amber'} size="small">{String(value)}</Pill> },
            { key: 'expires_at', header: 'Expires', render: value => <span title={formatTime(String(value))}>{relativeTime(String(value))}</span> },
            { key: 'pool_name', header: 'Pool' },
          ]} />
      </div>
      <RightPanel>
        {adding && isAdmin ? (
          <PanelSection title="Add pool" icon={Plus} action={<IconButton size="small" icon={X} label="Close" onClick={() => setAdding(false)} />}>
            <form className={styles.form} onSubmit={createPool}>
              {poolFields}
              <Button type="submit" variant="primary" disabled={busy}>Add pool</Button>
            </form>
          </PanelSection>
        ) : lease ? (
          <PanelSection title={`Lease ${lease.ip}`} icon={IdentificationCard} action={<IconButton size="small" icon={X} label="Close" onClick={() => setLeaseId(null)} />}>
            <StatRow caption="MAC" value={lease.mac} />
            <StatRow caption="Hostname" value={lease.hostname ?? '-'} />
            <StatRow caption="State" value={lease.state} />
            <StatRow caption="Expires" value={formatTime(lease.expires_at)} />
            {isAdmin && <div className={styles.actions}>
              <Button icon={ArrowCounterClockwise} disabled={busy} onClick={() => setPending({
                title: `Release ${lease.ip}?`, label: 'Release',
                body: `The address returns to the pool immediately and can be offered to another device. ${lease.mac} will need a new lease when it next renews.`,
                run: () => api.releaseDhcpLease(lease.id), success: `Released ${lease.ip}.`, after: () => setLeaseId(null),
              })}>Release lease</Button>
            </div>}
          </PanelSection>
        ) : reservation ? (
          <PanelSection title={`Reservation ${reservation.ip}`} icon={IdentificationCard} action={<IconButton size="small" icon={X} label="Close" onClick={() => setReservationId(null)} />}>
            <StatRow caption="MAC" value={reservation.mac} />
            <StatRow caption="Hostname" value={reservation.hostname ?? '-'} />
            {isAdmin && <div className={styles.actions}>
              <Button icon={Trash} disabled={busy} onClick={() => setPending({
                title: `Delete the reservation for ${reservation.mac}?`, label: 'Delete',
                body: `${reservation.mac} will no longer be guaranteed ${reservation.ip}; it gets a normal address from the range next time.`,
                run: () => api.deleteDhcpReservation(reservation.id), success: 'Reservation deleted.', after: () => setReservationId(null),
              })}>Delete reservation</Button>
            </div>}
          </PanelSection>
        ) : pool ? (
          <>
            <PanelSection title={pool.name} icon={Network} action={<IconButton size="small" icon={X} label="Close" onClick={() => setPoolId(null)} />}>
              {isAdmin ? (
                <form className={styles.form} onSubmit={savePool}>
                  {poolFields}
                  <div className={styles.actions}>
                    <Button type="submit" icon={FloppyDisk} disabled={busy}>Save pool</Button>
                    <Button type="button" icon={Trash} disabled={busy} onClick={() => setPending({
                      title: `Delete pool '${pool.name}'?`, label: 'Delete pool',
                      body: `This drops ${pool.active_lease_count} active lease(s) and ${pool.reservation_count} reservation(s). Those devices lose their addresses at their next renewal, and DHCP stops serving this network.`,
                      run: () => api.deleteDhcpPool(pool.id), success: `Pool '${pool.name}' deleted.`, after: () => setPoolId(null),
                    })}>Delete pool</Button>
                  </div>
                </form>
              ) : (
                <>
                  <StatRow caption="Subnet" value={pool.subnet} />
                  <StatRow caption="Range" value={`${pool.range_start} - ${pool.range_end}`} />
                  <StatRow caption="Gateway" value={pool.gateway} />
                  <StatRow caption="DNS" value={pool.dns_servers.join(', ')} />
                  <StatRow caption="Lease" value={`${pool.lease_seconds} s`} />
                </>
              )}
            </PanelSection>
            {isAdmin && (
              <PanelSection title="Add reservation" icon={Plus}>
                <form className={styles.form} onSubmit={addReservation}>
                  <label className={styles.field}>MAC address<TextInput required placeholder="aa:bb:cc:dd:ee:ff" value={mac} onChange={event => setMac(event.target.value)} /></label>
                  <span className={styles.help}>{HELP.mac}</span>
                  <label className={styles.field}>Reserved IP<TextInput required placeholder="192.168.50.10" value={reservedIp} onChange={event => setReservedIp(event.target.value)} /></label>
                  <span className={styles.help}>{HELP.reservedIp}</span>
                  <label className={styles.field}>Hostname<TextInput placeholder="optional" value={hostname} onChange={event => setHostname(event.target.value)} /></label>
                  <span className={styles.help}>{HELP.hostname}</span>
                  <Button type="submit" variant="primary" icon={Plus} disabled={busy}>Add reservation</Button>
                </form>
              </PanelSection>
            )}
          </>
        ) : (
          <PanelSection title="DHCP" icon={Network}>
            <p className={styles.help}>Select a pool to see its reservations and leases{isAdmin ? ', or add a pool' : ''}. Select a lease for details{isAdmin ? ' or to release it' : ''}.</p>
          </PanelSection>
        )}
        {message && <div role={message.ok ? 'status' : 'alert'} className={message.ok ? styles.success : styles.error}>{message.text}</div>}
      </RightPanel>
      <ConfirmDialog open={pending !== null} title={pending?.title ?? ''} confirmLabel={pending?.label ?? 'Confirm'}
        onCancel={() => setPending(null)}
        onConfirm={() => {
          if (pending) {
            const { run: action, success, after } = pending
            void run(action, success).then(ok => { if (ok) after?.() })
          }
          setPending(null)
        }}>
        {pending?.body}
      </ConfirmDialog>
    </>
  )
}
