import { useEffect, useState } from 'react'
import { CheckCircle, XCircle, AlertCircle } from 'lucide-react'

interface Props { message: string; type?: 'success' | 'error' | 'info'; onClose: () => void }

export default function Toast({ message, type = 'success', onClose }: Props) {
  useEffect(() => {
    const t = setTimeout(onClose, 3500)
    return () => clearTimeout(t)
  }, [onClose])

  const styles = {
    success: 'bg-green-900/80 border-green-700 text-green-200',
    error:   'bg-red-900/80 border-red-700 text-red-200',
    info:    'bg-blue-900/80 border-blue-700 text-blue-200',
  }
  const Icon = type === 'success' ? CheckCircle : type === 'error' ? XCircle : AlertCircle

  return (
    <div className={`fixed bottom-6 right-6 z-50 flex items-center gap-3 px-4 py-3 rounded-lg border text-sm shadow-xl ${styles[type]}`}>
      <Icon size={16} />
      {message}
      <button onClick={onClose} className="ml-2 opacity-60 hover:opacity-100">✕</button>
    </div>
  )
}
