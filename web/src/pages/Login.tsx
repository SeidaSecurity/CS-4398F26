import { useState } from 'react'
import type { FormEvent } from 'react'
import { SignIn } from '@phosphor-icons/react'
import { useAuth } from '../auth'
import { Button, TextInput } from '../components/ui'
import styles from './Login.module.css'

const mockMode = import.meta.env.VITE_API_MODE !== 'live'

/** Login screen (SRS 3.1.1). Errors are shown exactly as the server sends them (generic). */
export default function Login() {
  const { login } = useAuth()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setSubmitting(true)
    setError(null)
    try {
      await login(username.trim(), password)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Login failed. Try again.')
      setPassword('')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <main className={styles.page}>
      <form className={styles.card} onSubmit={submit} aria-label="Log in">
        <div className={styles.wordmark}>netmgr</div>
        <h1 className={styles.title}>Log in</h1>
        <label className={styles.field}>
          <span>Username</span>
          <TextInput autoFocus autoComplete="username" value={username}
            onChange={event => setUsername(event.target.value)} required />
        </label>
        <label className={styles.field}>
          <span>Password</span>
          <TextInput type="password" autoComplete="current-password" value={password}
            onChange={event => setPassword(event.target.value)} required />
        </label>
        {error && <div role="alert" className={styles.error}>{error}</div>}
        <Button type="submit" variant="primary" icon={SignIn} disabled={submitting || !username || !password}>
          {submitting ? 'Logging in…' : 'Log in'}
        </Button>
        {mockMode && (
          <p className={styles.hint}>Mock mode: log in as <b>admin</b> or <b>viewer</b> with any password.</p>
        )}
      </form>
    </main>
  )
}
