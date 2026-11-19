import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { api } from './api'
import type { CurrentUser } from './api'
import { UNAUTHORIZED_EVENT } from './api/session'

type AuthState = {
  /** undefined while checking the session, null when signed out */
  user: CurrentUser | null | undefined
  isAdmin: boolean
  login: (username: string, password: string) => Promise<void>
  logout: () => Promise<void>
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<CurrentUser | null | undefined>(undefined)

  useEffect(() => {
    let active = true
    api.me().then(
      current => { if (active) setUser(current) },
      () => { if (active) setUser(null) },
    )
    // Any 401 outside a login attempt means the session ended (expired, logged out, disabled).
    const signedOut = () => setUser(null)
    window.addEventListener(UNAUTHORIZED_EVENT, signedOut)
    return () => {
      active = false
      window.removeEventListener(UNAUTHORIZED_EVENT, signedOut)
    }
  }, [])

  const login = useCallback(async (username: string, password: string) => {
    setUser(await api.login(username, password))
  }, [])

  const logout = useCallback(async () => {
    try {
      await api.logout()
    } finally {
      setUser(null)
    }
  }, [])

  const value = useMemo(
    () => ({ user, isAdmin: user?.role === 'admin', login, logout }),
    [user, login, logout],
  )
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthState {
  const value = useContext(AuthContext)
  if (!value) throw new Error('useAuth must be used inside <AuthProvider>')
  return value
}
