import type { PointerEvent, ReactNode } from 'react'
import { AnimatePresence, motion, useMotionValue, useSpring, useTransform } from 'motion/react'
import { CircleCheck, CloudSun, Landmark, Luggage } from 'lucide-react'

const route = 'M40 230 C 140 90, 260 60, 330 150 S 470 250, 540 70'

/** Which planning stage a progress message describes (0 = just started). */
function stage(status?: string) {
  const s = (status ?? '').toLowerCase()
  if (/itinerary|packing|schedul|saving|ready/.test(s)) return 3
  if (/connect|route|transport/.test(s)) return 2
  if (/research|weather|places|tourism|router|attraction/.test(s)) return 1
  return 0
}

/**
 * Decorative travel scene: a dotted route, a plane flying it, and parallax clouds.
 * With a `status`, it doubles as a progress indicator: chips tick off as agents finish.
 */
export function RouteArt({ status }: { status?: string }) {
  const px = useMotionValue(0), py = useMotionValue(0)
  const sx = useSpring(px, { stiffness: 60, damping: 18 }), sy = useSpring(py, { stiffness: 60, damping: 18 })
  const farX = useTransform(sx, v => v * -10), farY = useTransform(sy, v => v * -8)
  const nearX = useTransform(sx, v => v * 22), nearY = useTransform(sy, v => v * 16)
  function track(e: PointerEvent<HTMLElement>) {
    const r = e.currentTarget.getBoundingClientRect()
    px.set((e.clientX - r.left) / r.width - .5); py.set((e.clientY - r.top) / r.height - .5)
  }
  const live = status !== undefined, at = stage(status)
  const chip = (cls: string, icon: ReactNode, label: string, done: boolean, style: object) =>
    <motion.div className={`float-chip ${cls}` + (live ? (done ? ' done' : ' waiting') : '')} style={style}>
      <AnimatePresence mode="wait" initial={false}>
        <motion.span key={String(live && done)} className="chip-icon" initial={{ scale: 0, rotate: -90 }} animate={{ scale: 1, rotate: 0 }} exit={{ scale: 0 }} transition={{ type: 'spring', stiffness: 500, damping: 22 }}>
          {live && done ? <CircleCheck size={14} /> : icon}
        </motion.span>
      </AnimatePresence>{label}
    </motion.div>

  return <motion.div className={'route-art' + (live ? ' live' : '')} aria-hidden onPointerMove={track} onPointerLeave={() => { px.set(0); py.set(0) }}
    initial={{ opacity: 0, scale: .96 }} animate={{ opacity: 1, scale: 1 }} transition={{ duration: .8, ease: [.22, 1, .36, 1] }}>
    <motion.div className="sun" style={{ x: farX, y: farY }} />
    <motion.div className="cloud c1" style={{ x: farX, y: farY }} />
    <motion.div className="cloud c2" style={{ x: nearX, y: nearY }} />
    <svg viewBox="0 0 580 300" className="route-map">
      <defs><linearGradient id="routeGrad" x1="0" x2="1"><stop offset="0" stopColor="#2a7f7f" /><stop offset=".6" stopColor="#e07a4a" /><stop offset="1" stopColor="#d2603a" /></linearGradient></defs>
      <motion.path d={route} fill="none" stroke="url(#routeGrad)" strokeWidth="2.5" strokeDasharray="2 9" strokeLinecap="round"
        initial={{ pathLength: 0 }} animate={{ pathLength: 1 }} transition={{ delay: .4, duration: 2.2, ease: 'easeInOut' }} />
      {live && <motion.path d={route} fill="none" stroke="url(#routeGrad)" strokeWidth="3" strokeLinecap="round" initial={{ pathLength: 0 }} animate={{ pathLength: [.12, .45, .7, .96][at] }} transition={{ duration: 1.2, ease: 'easeInOut' }} />}
      <path id="flight" d={route} fill="none" stroke="none" />
      {[[40, 230], [330, 150], [540, 70]].map(([cx, cy], i) => <g key={i}>
        <circle cx={cx} cy={cy} r="6" className="pin-ring" style={{ animationDelay: `${i * .7}s` }} />
        <circle cx={cx} cy={cy} r="5" fill={i === 2 ? '#d2603a' : '#2a7f7f'} stroke="#fffdf9" strokeWidth="2.5" />
      </g>)}
      <g className="plane">
        <path d="M-12 0 L10 -1.5 Q14 0 10 1.5 Z M-2 0 L-7 -9 L-3 -9 L5 0 L-3 9 L-7 9 Z M-11 0 L-14 -5 L-12 -5 L-8 0 L-12 5 L-14 5 Z" fill="#14363b" />
        <animateMotion dur={live ? '5s' : '9s'} repeatCount="indefinite" rotate="auto" keyPoints="0;1" keyTimes="0;1" calcMode="spline" keySplines=".45 0 .55 1"><mpath href="#flight" /></animateMotion>
      </g>
    </svg>
    {chip('f1', <CloudSun size={14} />, 'Weather checked', at >= 1, { x: nearX, y: nearY })}
    {chip('f2', <Landmark size={14} />, 'Places researched', at >= 2, { x: farX, y: farY })}
    {chip('f3', <Luggage size={14} />, 'Packing list', at >= 3, { x: nearX, y: nearY })}
  </motion.div>
}
