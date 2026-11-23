import React, { createContext, useContext, useState, useEffect } from 'react'
import { login as apiLogin } from '../services/api'

interface AuthCtx {
  isAuthenticated: boolean
  login: (token: string) => Promise<void>
  logout: () => void
  error: string
}

const AuthContext = createContext<AuthCtx>({} as AuthCtx)

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [isAuthenticated, setIsAuthenticated] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    const t = sessionStorage.getItem('admin_token')
    if (t) setIsAuthenticated(true)
  }, [])

  const login = async (token: string) => {
    try {
      await apiLogin(token)
      sessionStorage.setItem('admin_token', token)
      setIsAuthenticated(true)
      setError('')
    } catch {
      setError('Invalid admin token')
      throw new Error('Invalid admin token')
    }
  }

  const logout = () => {
    sessionStorage.removeItem('admin_token')
    setIsAuthenticated(false)
  }

  return (
    <AuthContext.Provider value={{ isAuthenticated, login, logout, error }}>
      {children}
    </AuthContext.Provider>
  )
}

export const useAuth = () => useContext(AuthContext)
