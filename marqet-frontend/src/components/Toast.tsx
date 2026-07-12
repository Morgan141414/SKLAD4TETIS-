import { createContext, useContext, useState, useCallback, useRef } from 'react'

interface Toast { id: number; msg: string; type: 'success' | 'error' | 'info' }
interface ToastCtx { show: (msg: string, type?: Toast['type']) => void }

const Ctx = createContext<ToastCtx>({ show: () => {} })
export const useToast = () => useContext(Ctx)

const css = `
.toast-wrap { position:fixed; bottom:24px; left:50%; transform:translateX(-50%); z-index:9999; display:flex; flex-direction:column; gap:8px; align-items:center; pointer-events:none; }
.toast { padding:12px 20px; border-radius:12px; font-size:14px; font-weight:600; color:#fff; pointer-events:auto; animation:slide-up .25s ease; white-space:nowrap; box-shadow:0 8px 24px rgba(0,0,0,.2); display:flex; align-items:center; gap:8px; max-width:90vw; }
@keyframes slide-up { from{opacity:0;transform:translateY(12px)} to{opacity:1;transform:translateY(0)} }
.toast-success { background:#059669; }
.toast-error { background:#DC2626; }
.toast-info { background:#5B4FE8; }
`

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])
  const nextId = useRef(1)

  const show = useCallback((msg: string, type: Toast['type'] = 'success') => {
    const id = nextId.current++
    setToasts(t => [...t, { id, msg, type }])
    setTimeout(() => setToasts(t => t.filter(x => x.id !== id)), 3000)
  }, [])

  const icons = { success: '✓', error: '✕', info: 'ℹ' }

  return (
    <Ctx.Provider value={{ show }}>
      {children}
      <style>{css}</style>
      <div className="toast-wrap">
        {toasts.map(t => (
          <div key={t.id} className={`toast toast-${t.type}`}>
            {icons[t.type]} {t.msg}
          </div>
        ))}
      </div>
    </Ctx.Provider>
  )
}
