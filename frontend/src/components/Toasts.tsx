import { createContext, useCallback, useContext, useRef, useState, type ReactNode } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { CircleCheck, Info, TriangleAlert, X } from 'lucide-react'

type Tone = 'error' | 'info' | 'success'
type Toast = { id: number; title: string; message?: string; tone: Tone }
type Notify = (toast: { title: string; message?: string; tone?: Tone }) => void

const ToastContext = createContext<Notify>(() => {})
export const useToast = () => useContext(ToastContext)
const duration = 7000
const icons = { error: <TriangleAlert size={18} />, info: <Info size={18} />, success: <CircleCheck size={18} /> }

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])
  const next = useRef(0)
  const dismiss = useCallback((id: number) => setToasts(list => list.filter(t => t.id !== id)), [])
  const notify = useCallback<Notify>(({ title, message, tone = 'error' }) => {
    const id = ++next.current
    // Repeating the same error replaces it instead of stacking duplicates.
    setToasts(list => [...list.filter(t => t.title !== title || t.message !== message), { id, title, message, tone }].slice(-4))
    setTimeout(() => dismiss(id), duration)
  }, [dismiss])

  return <ToastContext.Provider value={notify}>
    {children}
    <div className="toasts" aria-live="assertive">
      <AnimatePresence initial={false}>
        {toasts.map(t => <motion.div key={t.id} layout className={'toast ' + t.tone} role={t.tone === 'error' ? 'alert' : 'status'}
          initial={{ opacity: 0, y: -24, scale: .95 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, x: 60, scale: .95 }} transition={{ type: 'spring', stiffness: 380, damping: 30 }}>
          <span className="toast-icon">{icons[t.tone]}</span>
          <div className="toast-body"><strong>{t.title}</strong>{t.message && <p>{t.message}</p>}</div>
          <button className="toast-close" aria-label="Dismiss" onClick={() => dismiss(t.id)}><X size={15} /></button>
          <motion.span className="toast-timer" initial={{ scaleX: 1 }} animate={{ scaleX: 0 }} transition={{ duration: duration / 1000, ease: 'linear' }} />
        </motion.div>)}
      </AnimatePresence>
    </div>
  </ToastContext.Provider>
}
