import type { ReactNode } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { ArrowUpRight, Compass, Info, TriangleAlert } from 'lucide-react'

export const ease = [.22, 1, .36, 1] as const

export type Evidence = { id: string; provider: string; url: string | null; retrieved_at?: string; attribution?: string; attribution_url?: string; data?: { reference_only?: boolean; cache_status?: string; notice?: string; places?: { name: string; url?: string }[] } }

/** Live status line; the compass spins while agents are working. */
export function Status({ busy, failed, children }: { busy: boolean; failed?: boolean; children: ReactNode }) {
  return <div className={'status' + (failed ? ' failed' : '')} role={failed ? 'alert' : 'status'} aria-live="polite">
    <motion.span className="status-icon" animate={busy ? { rotate: 360 } : { rotate: 0 }} transition={busy ? { repeat: Infinity, duration: 2.4, ease: 'linear' } : { duration: .4 }}>
      {failed ? <TriangleAlert size={15} /> : <Compass size={15} />}
    </motion.span>
    <AnimatePresence mode="wait">
      <motion.span key={String(children)} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }} transition={{ duration: .25 }}>{children}</motion.span>
    </AnimatePresence>
  </div>
}

export function Notice({ children, tone = 'info', role }: { children: ReactNode; tone?: 'info' | 'error'; role?: string }) {
  return <motion.div className={'notice ' + tone} role={role} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: .35, ease }}>
    <span className="notice-icon">{tone === 'error' ? <TriangleAlert size={16} /> : <Info size={16} />}</span><div>{children}</div>
  </motion.div>
}

export function Sources({ evidence }: { evidence?: Evidence[] }) {
  const links = evidence?.filter(e => e.url) ?? []
  const places = evidence?.flatMap(e => e.data?.places ?? []).filter(p => p.url) ?? []
  if (!links.length) return null
  return <><div className="sources">{links.map((e, i) =>
    <motion.a key={e.id} href={e.url!} target="_blank" rel="noreferrer" initial={{ opacity: 0, scale: .9 }} animate={{ opacity: 1, scale: 1 }} transition={{ delay: i * .05 }} whileHover={{ y: -2 }}>
      {e.provider}<ArrowUpRight size={13} />
    </motion.a>)}</div>
    {links.filter(e => e.attribution && e.attribution_url).map(e => <p className="muted" key={'credit-' + e.id}><a href={e.attribution_url} target="_blank" rel="noreferrer">{e.attribution}</a></p>)}
    {links.filter(e => e.data?.reference_only || e.data?.cache_status === 'stale-cache').map(e => <p className="muted" key={'freshness-' + e.id}>
      {e.provider}{e.retrieved_at && ` · Reference dated ${new Date(e.retrieved_at).toLocaleDateString()}`}: {e.data?.notice}
    </p>)}
    {places.length > 0 && <details><summary>Place references ({places.length})</summary><div className="sources">{places.map((place, i) => <a key={place.url! + i} href={place.url} target="_blank" rel="noreferrer">{place.name}<ArrowUpRight size={13} /></a>)}</div></details>}
  </>
}

/** Fixed, decorative scenery behind the app: warm light, contour lines and drifting clouds. */
export function Backdrop() {
  return <div className="backdrop" aria-hidden>
    <div className="glow g1" /><div className="glow g2" /><div className="glow g3" />
    <svg className="contours" viewBox="0 0 800 600" preserveAspectRatio="xMidYMid slice">
      {Array.from({ length: 9 }, (_, i) => <path key={i} fill="none" stroke="currentColor" strokeWidth="1"
        d={`M-50 ${120 + i * 48} C 150 ${60 + i * 52}, 300 ${200 + i * 40}, 460 ${110 + i * 50} S 760 ${40 + i * 55}, 880 ${140 + i * 46}`} />)}
    </svg>
    <div className="drift d1" /><div className="drift d2" />
  </div>
}
