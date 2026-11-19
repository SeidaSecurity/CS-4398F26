import { useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { Check, HardDrives, ListChecks, Plus, Stack, Trash, UploadSimple, X } from '@phosphor-icons/react'
import { api, useApi } from '../api'
import type { ChangeStatus, ConfigPushResult, ConfigTemplate } from '../api'
import { RightPanel } from '../components/Layout'
import { Button, Checkbox, ConfirmDialog, PanelSection, Pill, SectionHeader, Select, StatRow, TextArea, TextInput, ToolCard } from '../components/ui'
import styles from './Push.module.css'

const STATUS_LABELS: Record<ChangeStatus, string> = {
  succeeded: 'Succeeded',
  unverified: 'Applied, unverified',
  rejected: 'Rejected by device',
  unreachable: 'Unreachable',
  credentials: 'Credential problem',
  not_found: 'Not in inventory',
  failed: 'Failed',
}

function templateVariables(configuration: string): string[] {
  return [...new Set(
    [...configuration.matchAll(/\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}/g)]
      .map(match => match[1]),
  )].sort()
}

export default function Push() {
  const devicesQuery = useApi(() => api.listDevices(), [])
  const statusesQuery = useApi(() => api.listDeviceStatus(), [])
  const templatesQuery = useApi(() => api.listConfigTemplates(), [])
  const devices = devicesQuery.data ?? []
  const templates = templatesQuery.data ?? []
  const statuses = new Map((statusesQuery.data ?? []).map(status => [status.device_id, status.state]))
  const [selectedIds, setSelectedIds] = useState<number[]>([])
  const [snippet, setSnippet] = useState('')
  const [selectedTemplateId, setSelectedTemplateId] = useState<number | ''>('')
  const [templateName, setTemplateName] = useState('')
  const [templateValues, setTemplateValues] = useState<Record<string, string>>({})
  const [savingTemplate, setSavingTemplate] = useState(false)
  const [deletingTemplate, setDeletingTemplate] = useState(false)
  const [templateError, setTemplateError] = useState<string | null>(null)
  const [templateSuccess, setTemplateSuccess] = useState<string | null>(null)
  const [previewConfiguration, setPreviewConfiguration] = useState<string | null>(null)
  const [preparingPush, setPreparingPush] = useState(false)
  const [operator, setOperator] = useState('operator')
  const [confirming, setConfirming] = useState(false)
  const [pushing, setPushing] = useState(false)
  const pushInFlight = useRef(false)
  const [results, setResults] = useState<ConfigPushResult[] | null>(null)
  const [pushError, setPushError] = useState<string | null>(null)
  const [templateToDelete, setTemplateToDelete] = useState<ConfigTemplate | null>(null)
  const targets = devices.filter(device => selectedIds.includes(device.id))
  const allSelected = devices.length > 0 && targets.length === devices.length
  const disabled = !targets.length || !snippet.trim() || pushing || preparingPush
  const placeholders = templateVariables(snippet)
  const error = pushError ?? devicesQuery.error?.message ?? statusesQuery.error?.message
    ?? templatesQuery.error?.message

  function chooseTemplate(value: string) {
    setTemplateError(null)
    setTemplateSuccess(null)
    setPreviewConfiguration(null)
    if (!value) {
      setSelectedTemplateId('')
      setTemplateName('')
      setTemplateValues(Object.fromEntries(templateVariables(snippet).map(name => [name, ''])))
      return
    }
    const template = templates.find(item => item.id === Number(value))
    if (!template) return
    setSelectedTemplateId(template.id)
    setTemplateName(template.name)
    setSnippet(template.configuration)
    setTemplateValues(Object.fromEntries(templateVariables(template.configuration).map(name => [name, ''])))
  }

  async function saveTemplate() {
    if (savingTemplate || !templateName.trim() || !snippet.trim()) return
    setSavingTemplate(true)
    setTemplateError(null)
    setTemplateSuccess(null)
    try {
      const payload = { name: templateName.trim(), configuration: snippet }
      const saved = selectedTemplateId === ''
        ? await api.createConfigTemplate(payload)
        : await api.updateConfigTemplate(selectedTemplateId, payload)
      setSelectedTemplateId(saved.id)
      setTemplateName(saved.name)
      setSnippet(saved.configuration)
      setTemplateValues(current => Object.fromEntries(
        templateVariables(saved.configuration).map(name => [name, current[name] ?? '']),
      ))
      setTemplateSuccess(`Template "${saved.name}" saved.`)
      templatesQuery.reload()
    } catch (reason) {
      setTemplateError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setSavingTemplate(false)
    }
  }

  async function deleteTemplate() {
    if (!templateToDelete || deletingTemplate) return
    setDeletingTemplate(true)
    setTemplateError(null)
    setTemplateSuccess(null)
    try {
      await api.deleteConfigTemplate(templateToDelete.id)
      if (selectedTemplateId === templateToDelete.id) {
        setSelectedTemplateId('')
        setTemplateName('')
      }
      setTemplateToDelete(null)
      setTemplateSuccess(`Template "${templateToDelete.name}" deleted.`)
      templatesQuery.reload()
    } catch (reason) {
      setTemplateError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setDeletingTemplate(false)
    }
  }

  async function preparePush() {
    if (disabled) return
    setPreparingPush(true)
    setPushError(null)
    setResults(null)
    try {
      const hasTemplateSyntax = snippet.includes('{{') || snippet.includes('}}')
      const configuration = selectedTemplateId !== '' || hasTemplateSyntax
        ? (await api.renderConfigTemplate({ configuration: snippet, variables: templateValues })).configuration
        : snippet
      setPreviewConfiguration(configuration)
      setConfirming(true)
    } catch (reason) {
      setPushError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setPreparingPush(false)
    }
  }

  async function push() {
    if (disabled || pushInFlight.current || previewConfiguration === null) return
    pushInFlight.current = true
    setConfirming(false)
    setPushing(true)
    setPushError(null)
    setResults(null)
    try {
      setResults(await api.pushConfig({ device_ids: targets.map(device => device.id), configuration: previewConfiguration, operator }))
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
          onChange={event => {
            const configuration = event.target.value
            setSnippet(configuration)
            setPreviewConfiguration(null)
            setTemplateValues(current => Object.fromEntries(
              templateVariables(configuration).map(name => [name, current[name] ?? '']),
            ))
          }}
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
        <PanelSection title="Templates" icon={Stack}>
          <Select
            aria-label="Configuration template"
            value={selectedTemplateId === '' ? '' : String(selectedTemplateId)}
            onChange={chooseTemplate}
            options={[
              { value: '', label: 'Manual snippet' },
              ...templates.map(template => ({ value: String(template.id), label: template.name })),
            ]}
          />
          <label className={styles.templateName}>
            Template name
            <TextInput
              aria-label="Template name"
              value={templateName}
              onChange={event => {
                setTemplateName(event.target.value)
                setTemplateError(null)
                setTemplateSuccess(null)
              }}
              placeholder="e.g. Access port"
            />
          </label>
          <div className={styles.templateActions}>
            <Button icon={selectedTemplateId === '' ? Plus : Check} onClick={saveTemplate} disabled={savingTemplate || !templateName.trim() || !snippet.trim()}>
              {selectedTemplateId === '' ? 'Save template' : 'Update template'}
            </Button>
            <Button onClick={() => {
              setSelectedTemplateId('')
              setTemplateName('')
              setTemplateValues(Object.fromEntries(placeholders.map(name => [name, ''])))
              setTemplateError(null)
              setTemplateSuccess(null)
              setPreviewConfiguration(null)
            }}>New</Button>
            {selectedTemplateId !== '' && (
              <Button
                icon={Trash}
                onClick={() => setTemplateToDelete(templates.find(item => item.id === selectedTemplateId) ?? null)}
                disabled={!templates.some(item => item.id === selectedTemplateId)}
              >Delete</Button>
            )}
          </div>
          {placeholders.map(name => (
            <label key={name} className={styles.templateName}>
              {name}
              <TextInput
                aria-label={`Template value ${name}`}
                value={templateValues[name] ?? ''}
                onChange={event => {
                  setTemplateValues(values => ({ ...values, [name]: event.target.value }))
                  setPreviewConfiguration(null)
                  setTemplateError(null)
                }}
              />
            </label>
          ))}
          <div className={styles.templateHelp}>Use {'{{ variable_name }}'} in the snippet for values to fill in.</div>
          {templateError && <div role="alert" className={styles.error}>{templateError}</div>}
          {templateSuccess && <div role="status" className={styles.success}>{templateSuccess}</div>}
        </PanelSection>
        <PanelSection title="Push" icon={UploadSimple}>
          <ToolCard title="Operator">
            <TextInput aria-label="Operator" value={operator} onChange={event => setOperator(event.target.value)} />
          </ToolCard>
          <Button className={styles.pushButton} variant="primary" icon={UploadSimple} disabled={disabled} onClick={preparePush}>
            {preparingPush ? 'Preparing…' : `Preview push to ${targets.length} ${targets.length === 1 ? 'device' : 'devices'}`}
          </Button>
          {error && <div role="alert" className={styles.error}>{error}</div>}
        </PanelSection>
        {results !== null && <PanelSection title="Results" icon={ListChecks}>
          {results.map(result => {
            const name = devices.find(device => device.id === result.device_id)?.name ?? String(result.device_id)
            const succeeded = result.status === 'succeeded'
            const tone = succeeded ? 'green' : result.status === 'unverified' ? 'amber' : 'red'
            const row = <StatRow caption={name} value={<Pill tone={tone} icon={succeeded ? Check : X}>{succeeded ? `v${result.before_version} → v${result.after_version}` : STATUS_LABELS[result.status]}</Pill>} />
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
        <div className={styles.confirmation}>
          <div><strong>Targets:</strong> {targets.map(device => device.name).join(', ')}</div>
          <div><strong>Configuration snippet:</strong></div>
          <pre className={styles.preview}>{previewConfiguration}</pre>
        </div>
      </ConfirmDialog>
      <ConfirmDialog
        open={templateToDelete !== null}
        title={`Delete template "${templateToDelete?.name ?? ''}"?`}
        confirmLabel="Delete"
        onConfirm={deleteTemplate}
        onCancel={() => setTemplateToDelete(null)}
      >
        This permanently deletes the saved template. It does not affect configurations already pushed to devices.
      </ConfirmDialog>
    </>
  )
}
