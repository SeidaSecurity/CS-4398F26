import { useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { ArrowCounterClockwise, ArrowRight, ArrowsClockwise, Check, Clock, ClockCounterClockwise, DownloadSimple, HardDrives } from '@phosphor-icons/react'
import { api, useApi } from '../api'
import type { ConfigPushResult, ConfigVersion } from '../api'
import { RightPanel } from '../components/Layout'
import { ConfirmDialog, FilterBar, IconButton, PanelSection, Pill, SectionHeader, Select } from '../components/ui'
import { sideBySide } from '../lib/diff'
import { formatTime, relativeTime } from '../lib/format'
import styles from './History.module.css'

function versionNumber(value: string | null): number | undefined {
  if (value === null || !/^\d+$/.test(value)) return undefined
  const number = Number(value)
  return Number.isSafeInteger(number) && number > 0 ? number : undefined
}

function metadata(version: ConfigVersion): string {
  return `v${version.version} · ${version.source} · ${formatTime(version.created_at)} · ${version.operator}`
}

export default function History() {
  const [searchParams, setSearchParams] = useSearchParams()
  const devicesQuery = useApi(() => api.listDevices(), [])
  const devices = [...(devicesQuery.data ?? [])].sort((a, b) => a.name.localeCompare(b.name))
  const device = devices.find(item => String(item.id) === searchParams.get('device')) ?? devices[0]
  const deviceId = device?.id
  const activeDevice = useRef(deviceId)
  activeDevice.current = deviceId
  const [retrieving, setRetrieving] = useState(false)
  const retrieveInFlight = useRef(false)
  const [retrieveError, setRetrieveError] = useState<{ deviceId: number; message: string } | null>(null)
  const [restoreTarget, setRestoreTarget] = useState<number | null>(null)
  const [restoring, setRestoring] = useState(false)
  const restoreInFlight = useRef(false)
  const [restoreResult, setRestoreResult] = useState<{
    deviceId: number
    version: number
    result?: ConfigPushResult
    error?: string
  } | null>(null)

  const versionsQuery = useApi(async () => ({
    deviceId,
    versions: deviceId === undefined ? [] : await api.listConfigVersions(deviceId),
  }), [deviceId])
  const versions = versionsQuery.data && versionsQuery.data.deviceId === deviceId
    ? [...versionsQuery.data.versions].sort((a, b) => b.version - a.version)
    : []
  const compare = versionNumber(searchParams.get('compare')) ?? versions[0]?.version
  const base = versionNumber(searchParams.get('base'))
    ?? versions.find(version => compare !== undefined && version.version < compare)?.version
    ?? compare
  const single = versions.length === 1

  const configQuery = useApi(async () => {
    if (deviceId === undefined || compare === undefined || base === undefined) return null
    const [left, right] = await Promise.all([
      api.getConfigVersion(deviceId, base),
      base === compare ? Promise.resolve(null) : api.getConfigVersion(deviceId, compare),
    ])
    return { deviceId, base, compare, left, right: right ?? left }
  }, [deviceId, base, compare])
  const config = configQuery.data && configQuery.data.deviceId === deviceId
    && configQuery.data.base === base && configQuery.data.compare === compare ? configQuery.data : null
  const diff = useMemo(() => sideBySide(config?.left.configuration ?? '', config?.right.configuration ?? ''), [config])
  const halfWidth = diff.rows.reduce((width, row) => Math.max(width,
    64 + 7 * (row.left?.text.length ?? 0), 64 + 7 * (row.right?.text.length ?? 0)), 160)
  const error = (retrieveError && retrieveError.deviceId === deviceId ? retrieveError.message : null)
    ?? devicesQuery.error?.message ?? versionsQuery.error?.message ?? configQuery.error?.message
  const currentRestoreResult = restoreResult?.deviceId === deviceId ? restoreResult : null
  const versionOptions = versions.map(version => ({ value: String(version.version), label: `v${version.version}` }))

  function selectVersions(nextCompare: number, nextBase: number) {
    setSearchParams(params => {
      const next = new URLSearchParams(params)
      if (deviceId !== undefined) next.set('device', String(deviceId))
      next.set('base', String(nextBase))
      next.set('compare', String(nextCompare))
      return next
    })
  }

  function reload() {
    setRetrieveError(null)
    devicesQuery.reload()
    versionsQuery.reload()
    configQuery.reload()
  }

  async function retrieve() {
    if (deviceId === undefined || retrieveInFlight.current) return
    retrieveInFlight.current = true
    setRetrieving(true)
    setRetrieveError(null)
    try {
      const result = await api.retrieveConfig(deviceId, 'operator')
      const updatedVersions = await api.listConfigVersions(deviceId)
      if (activeDevice.current !== deviceId) return
      const previous = updatedVersions.filter(version => version.version < result.version)
        .sort((a, b) => b.version - a.version)[0]
      selectVersions(result.version, previous?.version ?? result.version)
      versionsQuery.reload()
      configQuery.reload()
    } catch (reason) {
      setRetrieveError({ deviceId, message: reason instanceof Error ? reason.message : String(reason) })
    } finally {
      retrieveInFlight.current = false
      setRetrieving(false)
    }
  }

  async function restore() {
    if (deviceId === undefined || restoreTarget === null || restoreInFlight.current) return
    const targetVersion = restoreTarget
    restoreInFlight.current = true
    setRestoring(true)
    setRestoreTarget(null)
    setRestoreResult(null)
    try {
      const result = await api.restoreConfig(deviceId, targetVersion, 'operator')
      if (activeDevice.current !== deviceId) return
      if (result.status !== 'succeeded' || result.after_version === null) {
        setRestoreResult({
          deviceId,
          version: targetVersion,
          result,
          error: result.error ?? 'Configuration restore failed',
        })
        return
      }
      setRestoreResult({ deviceId, version: targetVersion, result })
      selectVersions(result.after_version, targetVersion)
      versionsQuery.reload()
      configQuery.reload()
    } catch (reason) {
      if (activeDevice.current === deviceId) {
        setRestoreResult({
          deviceId,
          version: targetVersion,
          error: reason instanceof Error ? reason.message : String(reason),
        })
      }
    } finally {
      restoreInFlight.current = false
      setRestoring(false)
    }
  }

  return (
    <>
      <FilterBar>
        <Select icon={HardDrives} aria-label="Device" value={deviceId === undefined ? '' : String(deviceId)}
          options={devices.map(item => ({ value: String(item.id), label: item.name }))}
          disabled={!devices.length || retrieving || restoring}
          onChange={value => {
            setRetrieveError(null)
            setSearchParams(params => {
              const next = new URLSearchParams(params)
              next.set('device', value)
              next.delete('base')
              next.delete('compare')
              return next
            })
          }} />
        <Select aria-label="Base version" value={base === undefined ? '' : String(base)} options={versionOptions}
          disabled={!versions.length || retrieving || restoring} onChange={value => { if (compare !== undefined) selectVersions(compare, Number(value)) }} />
        <ArrowRight size={12} color="var(--gray-400)" aria-hidden="true" />
        <Select aria-label="Compare version" value={compare === undefined ? '' : String(compare)} options={versionOptions}
          disabled={!versions.length || retrieving || restoring} onChange={value => { if (base !== undefined) selectVersions(Number(value), base) }} />
        <IconButton size="small" icon={ArrowsClockwise} label="Refresh" onClick={reload} disabled={retrieving || restoring} />
      </FilterBar>
      {error && <div role="alert" className={styles.error}>{error}</div>}
      {config && <div className={styles.content}>
        <SectionHeader title={single ? `v${compare}` : `v${base} → v${compare}`}>
          {!single && <span className={styles.counts}><span className={styles.addedCount}>+{diff.added}</span> <span className={styles.removedCount}>−{diff.removed}</span></span>}
        </SectionHeader>
        <div className={styles.diffScroll}>
          <div style={{ minWidth: halfWidth * (single ? 1 : 2) }}>
            <div className={[styles.metadata, single && styles.singleMetadata].filter(Boolean).join(' ')}>
              <div>{metadata(config.left)}</div>
              {!single && <div>{metadata(config.right)}</div>}
            </div>
            <table className={styles.diff} aria-label={single ? `Version ${compare}` : `Version ${base} compared with version ${compare}`}>
              <colgroup>
                <col className={styles.numberColumn} />
                <col className={styles.textColumn} />
                {!single && <><col className={styles.numberColumn} /><col className={styles.textColumn} /></>}
              </colgroup>
              <tbody>
                {diff.rows.map((row, index) => <tr key={index}>
                  <td className={styles.lineNumber}>{row.left?.n}</td>
                  <td className={!single && (row.kind === 'removed' || row.kind === 'changed') ? styles.removed : undefined}>{row.left?.text}</td>
                  {!single && <>
                    <td className={[styles.lineNumber, styles.divider].join(' ')}>{row.right?.n}</td>
                    <td className={row.kind === 'added' || row.kind === 'changed' ? styles.added : undefined}>{row.right?.text}</td>
                  </>}
                </tr>)}
              </tbody>
            </table>
          </div>
        </div>
      </div>}
      <RightPanel>
        <PanelSection title="Versions" icon={ClockCounterClockwise} action={
          <IconButton size="small" icon={DownloadSimple} label="Retrieve running config" onClick={retrieve} disabled={deviceId === undefined || retrieving || restoring} />
        }>
          <div className={styles.versions}>
            {versions.map((version, index) => <div key={version.id} className={styles.versionRow}>
              <button type="button"
                className={[styles.version, version.version === compare && styles.compareVersion, version.version === base && styles.baseVersion].filter(Boolean).join(' ')}
                aria-pressed={version.version === compare} disabled={retrieving || restoring}
                onClick={() => selectVersions(version.version, versions[index + 1]?.version ?? version.version)}>
                <span className={styles.versionLabel}>v{version.version}</span>
                <Pill tone="gray" size="small" icon={version.source === 'push' ? Check : Clock}>{version.source}</Pill>
                <span className={styles.time}>{relativeTime(version.created_at)}</span>
              </button>
              <IconButton
                size="small"
                icon={ArrowCounterClockwise}
                label={`Restore version ${version.version}`}
                title={`Restore version ${version.version}`}
                disabled={retrieving || restoring}
                onClick={() => {
                  setRestoreResult(null)
                  setRestoreTarget(version.version)
                }}
              />
            </div>)}
          </div>
          {currentRestoreResult?.result?.status === 'succeeded' && (
            <div role="status" className={styles.restoreSuccess}>
              Restored v{currentRestoreResult.version} as v{currentRestoreResult.result.after_version}.
            </div>
          )}
          {currentRestoreResult?.error && (
            <div role="alert" className={styles.error}>{currentRestoreResult.error}</div>
          )}
        </PanelSection>
      </RightPanel>
      <ConfirmDialog
        open={restoreTarget !== null}
        title={`Restore configuration v${restoreTarget ?? ''}?`}
        confirmLabel="Restore"
        onConfirm={restore}
        onCancel={() => setRestoreTarget(null)}
      >
        This applies the saved configuration to {device?.name ?? 'the selected device'}.
        The current configuration will be backed up first, and the restored result will be saved as a new version.
      </ConfirmDialog>
    </>
  )
}
