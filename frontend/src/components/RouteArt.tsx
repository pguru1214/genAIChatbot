import type { PointerEvent } from 'react'
import { motion, useMotionValue, useSpring, useTransform } from 'motion/react'
import { CloudSun, Landmark, Luggage } from 'lucide-react'

const route = 'M40 230 C 140 90, 260 60, 330 150 S 470 250, 540 70'

/** Decorative travel scene: a dotted route, a plane flying it, and parallax clouds. */
export function RouteArt() {
  const px = useMotionValue(0), py = useMotionValue(0)
  const sx = useSpring(px, { stiffness: 60, damping: 18 }), sy = useSpring(py, { stiffness: 60, damping: 18 })
  const farX = useTransform(sx, v => v * -10), farY = useTransform(sy, v => v * -8)
  const nearX = useTransform(sx, v => v * 22), nearY = useTransform(sy, v => v * 16)
  function track(e: PointerEvent<HTMLElement>) {
    const r = e.currentTarget.getBoundingClientRect()
    px.set((e.clientX - r.left) / r.width - .5); py.set((e.clientY - r.top) / r.height - .5)
  }
  return <motion.div className="route-art" aria-hidden onPointerMove={track} onPointerLeave={() => { px.set(0); py.set(0) }}
    initial={{ opacity: 0, scale: .96 }} animate={{ opacity: 1, scale: 1 }} transition={{ duration: .8, ease: [.22, 1, .36, 1] }}>
    <motion.div className="sun" style={{ x: farX, y: farY }} />
    <motion.div className="cloud c1" style={{ x: farX, y: farY }} />
    <motion.div className="cloud c2" style={{ x: nearX, y: nearY }} />
    <svg viewBox="0 0 580 300" className="route-map">
      <defs><linearGradient id="routeGrad" x1="0" x2="1"><stop offset="0" stopColor="#2a7f7f" /><stop offset=".6" stopColor="#e07a4a" /><stop offset="1" stopColor="#d2603a" /></linearGradient></defs>
      <motion.path d={route} fill="none" stroke="url(#routeGrad)" strokeWidth="2.5" strokeDasharray="2 9" strokeLinecap="round"
        initial={{ pathLength: 0 }} animate={{ pathLength: 1 }} transition={{ delay: .4, duration: 2.2, ease: 'easeInOut' }} />
      <path id="flight" d={route} fill="none" stroke="none" />
      {[[40, 230], [330, 150], [540, 70]].map(([cx, cy], i) => <g key={i}>
        <circle cx={cx} cy={cy} r="6" className="pin-ring" style={{ animationDelay: `${i * .7}s` }} />
        <circle cx={cx} cy={cy} r="5" fill={i === 2 ? '#d2603a' : '#2a7f7f'} stroke="#fffdf9" strokeWidth="2.5" />
      </g>)}
      <g className="plane">
        <path d="M-12 0 L10 -1.5 Q14 0 10 1.5 Z M-2 0 L-7 -9 L-3 -9 L5 0 L-3 9 L-7 9 Z M-11 0 L-14 -5 L-12 -5 L-8 0 L-12 5 L-14 5 Z" fill="#14363b" />
        <animateMotion dur="9s" repeatCount="indefinite" rotate="auto" keyPoints="0;1" keyTimes="0;1" calcMode="spline" keySplines=".45 0 .55 1"><mpath href="#flight" /></animateMotion>
      </g>
    </svg>
    <motion.div className="float-chip f1" style={{ x: nearX, y: nearY }}><CloudSun size={14} /> Weather checked</motion.div>
    <motion.div className="float-chip f2" style={{ x: farX, y: farY }}><Landmark size={14} /> Places researched</motion.div>
    <motion.div className="float-chip f3" style={{ x: nearX, y: nearY }}><Luggage size={14} /> Packing list</motion.div>
  </motion.div>
}
