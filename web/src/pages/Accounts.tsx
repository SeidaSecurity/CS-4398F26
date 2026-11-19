import { useState } from 'react'
import type { FormEvent } from 'react'
import { Key, Plus, Prohibit, ShieldCheck, UserCircle, X } from '@phosphor-icons/react'
import { api, useApi } from '../api'
import type { Role, UserAccount, UserUpdate } from '../api'
import { useAuth } from '../auth'
import { RightPanel } from '../components/Layout'
import { Button, ConfirmDialog, DataTable, IconButton, PanelSection, Pill, Select, StatRow, TextInput } from '../components/ui'
import { formatTime } from '../lib/format'
import styles from './Accounts.module.css'

const roleOptions = [
  { value: 'viewer', label: 'Viewer (read-only)' },
  { value: 'admin', label: 'Admin' },
]

/** Account management (R7.4). Admin-only; the server enforces the same rules. */
export default function Accounts() {
  const { user: me } = useAuth()
  const usersQuery = useApi(() => api.listUsers(), [])
  const users = usersQuery.data ?? []
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const selected = users.find(user => user.id === selectedId) ?? null

  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [role, setRole] = useState<Role>('viewer')
  const [newPassword, setNewPassword] = useState('')
  const [pending, setPending] = useState<{ title: string; body: string; patch: UserUpdate } | null>(null)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null)

  const run = async (action: () => Promise<unknown>, success: string) => {
    setBusy(true)
    setMessage(null)
    try {
      await action()
      setMessage({ ok: true, text: success })
      usersQuery.reload()
      return true
    } catch (reason) {
      setMessage({ ok: false, text: reason instanceof Error ? reason.message : String(reason) })
      return false
    } finally {
      setBusy(false)
    }
  }

  const create = async (event: FormEvent) => {
    event.preventDefault()
    const created = await run(() => api.createUser({ username: username.trim(), password, role }),
      `Created ${role} '${username.trim()}'.`)
    if (created) { setUsername(''); setPassword(''); setRole('viewer') }
  }

  const update = (target: UserAccount, patch: UserUpdate, success: string) =>
    run(() => api.updateUser(target.id, patch), success)

  return (
    <>
      {usersQuery.error && <div role="alert" className={styles.error}>{usersQuery.error.message}</div>}
      <div className={styles.content}>
        <DataTable aria-label="Accounts" rows={users} rowKey="id" selectedKey={selectedId ?? undefined}
          onRowClick={user => { setSelectedId(user.id); setMessage(null); setNewPassword('') }}
          columns={[
            { key: 'username', header: 'Username', render: (_, user) => (
              <span className={styles.name}>{user.username}{user.id === me?.id && <span className={styles.you}>you</span>}</span>
            ) },
            { key: 'role', header: 'Role', render: value => (
              <Pill tone={value === 'admin' ? 'green' : 'gray'} size="small">{String(value)}</Pill>
            ) },
            { key: 'disabled', header: 'Status', render: value => (
              <Pill tone={value ? 'red' : 'green'} size="small">{value ? 'Disabled' : 'Active'}</Pill>
            ) },
            { key: 'created_at', header: 'Created', render: value => formatTime(String(value)) },
          ]} />
      </div>
      <RightPanel>
        {selected ? (
          <PanelSection title={selected.username} icon={UserCircle}
            action={<IconButton size="small" icon={X} label="Close" onClick={() => setSelectedId(null)} />}>
            <StatRow caption="Role" value={selected.role} />
            <StatRow caption="Status" value={selected.disabled ? 'Disabled' : 'Active'} />
            <div className={styles.actions}>
              <Button icon={ShieldCheck} disabled={busy} onClick={() => {
                const next: Role = selected.role === 'admin' ? 'viewer' : 'admin'
                if (next === 'viewer') {
                  setPending({ title: `Make '${selected.username}' a viewer?`, body: 'They will lose the ability to change devices, configurations, and accounts.', patch: { role: 'viewer' } })
                } else {
                  void update(selected, { role: 'admin' }, `'${selected.username}' is now an admin.`)
                }
              }}>{selected.role === 'admin' ? 'Make viewer' : 'Make admin'}</Button>
              <Button icon={Prohibit} disabled={busy} onClick={() => {
                if (selected.disabled) {
                  void update(selected, { disabled: false }, `'${selected.username}' can log in again.`)
                } else {
                  setPending({ title: `Disable '${selected.username}'?`, body: 'They are logged out immediately and cannot log in until re-enabled.', patch: { disabled: true } })
                }
              }}>{selected.disabled ? 'Enable' : 'Disable'}</Button>
            </div>
            <form className={styles.form} onSubmit={async event => {
              event.preventDefault()
              if (await update(selected, { password: newPassword }, `Password reset for '${selected.username}'.`)) setNewPassword('')
            }}>
              <label className={styles.field}><span>New password</span>
                <TextInput type="password" autoComplete="new-password" value={newPassword} onChange={event => setNewPassword(event.target.value)} />
              </label>
              <Button type="submit" icon={Key} disabled={busy || !newPassword}>Reset password</Button>
            </form>
          </PanelSection>
        ) : (
          <PanelSection title="Add account" icon={Plus}>
            <form className={styles.form} onSubmit={create}>
              <label className={styles.field}><span>Username</span>
                <TextInput autoComplete="off" value={username} onChange={event => setUsername(event.target.value)} />
              </label>
              <label className={styles.field}><span>Password</span>
                <TextInput type="password" autoComplete="new-password" value={password} onChange={event => setPassword(event.target.value)} />
              </label>
              <span className={styles.help}>8-64 characters, not a common password, not the username.</span>
              <label className={styles.field}><span>Role</span>
                <Select aria-label="Role" value={role} options={roleOptions} onChange={value => setRole(value as Role)} />
              </label>
              <Button type="submit" variant="primary" icon={Plus} disabled={busy || !username.trim() || !password}>Add account</Button>
            </form>
          </PanelSection>
        )}
        {message && <div role={message.ok ? 'status' : 'alert'} className={message.ok ? styles.success : styles.error}>{message.text}</div>}
      </RightPanel>
      <ConfirmDialog open={pending !== null} title={pending?.title ?? ''} confirmLabel="Confirm"
        onCancel={() => setPending(null)}
        onConfirm={() => {
          if (selected && pending) void update(selected, pending.patch, 'Account updated.')
          setPending(null)
        }}>
        {pending?.body}
      </ConfirmDialog>
    </>
  )
}
