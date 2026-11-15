import { useEffect, useId, useLayoutEffect, useMemo, useRef, useState, type PointerEvent, type ReactNode } from 'react'
import { AnimatePresence, animate, motion, useMotionValue, useMotionValueEvent, useSpring, useTransform } from 'motion/react'
import { BusFront, CarFront, Navigation, Plane, Ship, TrainFront } from 'lucide-react'
import type { TransportMode, TransportOption } from '../types'
import { travelModes, type Stop } from '../lib/trip'
import { ease } from './ui'

const W = 640, H = 260, PX = 76, PY = 60
type XY = { x: number; y: number }
type Leg = { a: XY; b: XY; seg: string; mode: TransportMode }

export const modeIcon = (mode: TransportMode, size = 16) =>
  mode === 'flight' ? <Plane size={size} /> : mode === 'train' ? <TrainFront size={size} /> : mode === 'bus' ? <BusFront size={size} />
    : mode === 'sea' ? <Ship size={size} /> : mode === 'local' ? <Navigation size={size} /> : <CarFront size={size} />
export const modeLabel = (mode: TransportMode) => travelModes.find(m => m.id === mode)?.label ?? (mode === 'sea' ? 'Ferry' : 'Local')

/**
 * Lay stops out along their real compass bearings (when geocoded), with schematic leg
 * lengths so a 500 km journey and a 15 km hop are both legible, then fit to the card.
 */
function layout(stops: Stop[]): XY[] {
  if (stops.length === 0) return []
  if (stops.length === 1) return [{ x: W / 2, y: H / 2 }]
  const raw: XY[] = [{ x: 0, y: 0 }]
  for (let i = 1; i < stops.length; i++) {
    const a = stops[i - 1].point, b = stops[i].point
    let dx = 1, dy = i % 2 ? -.34 : .34
    if (a && b) {
      const rx = (b.lon - a.lon) * Math.cos(((a.lat + b.lat) / 2) * Math.PI / 180), ry = -(b.lat - a.lat)
      const len = Math.hypot(rx, ry)
      if (len > .002) { dx = rx / len; dy = ry / len }
    }
    // Keep each leg reading across the card instead of stacking pins vertically.
    if (Math.abs(dx) < .5) { dx = .5 * (dx < 0 ? -1 : 1); dy = Math.sign(dy || 1) * Math.sqrt(1 - .25) }
    const len = i === 1 && stops[0].kind === 'origin' ? 1.7 : 1
    // A leg that doubles back onto an earlier stop is turned a little so every pin stays visible.
    const end = (angle: number) => {
      const c = Math.cos(angle), s = Math.sin(angle)
      return { x: raw[i - 1].x + (dx * c - dy * s) * len, y: raw[i - 1].y + (dx * s + dy * c) * len }
    }
    const clear = (p: XY) => raw.slice(0, -1).every(q => Math.hypot(p.x - q.x, p.y - q.y) > .55)
    const turn = [0, .6, -.6, 1, -1, 1.4, -1.4].find(a => clear(end(a))) ?? 0
    raw.push(end(turn))
  }
  const xs = raw.map(p => p.x), ys = raw.map(p => p.y)
  const [minX, maxX, minY, maxY] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)]
  const s = Math.min((W - 2 * PX) / Math.max(maxX - minX, 1e-6), (H - 2 * PY) / Math.max(maxY - minY, 1e-6))
  const ox = (W - (maxX - minX) * s) / 2 - minX * s, oy = (H - (maxY - minY) * s) / 2 - minY * s
  return raw.map(p => ({ x: p.x * s + ox, y: p.y * s + oy }))
}

type Side = 'above' | 'below' | 'right' | 'left'
/** Place each stop label on the first side that overlaps no other label or pin. */
function placeLabels(pts: XY[], labels: string[]): Side[] {
  // Pins, plus the caption chip in the top-left corner.
  const boxes: [number, number, number, number][] = [[0, 0, 150, 40], ...pts.map(p => [p.x - 9, p.y - 9, p.x + 9, p.y + 9] as [number, number, number, number])]
  const hit = (r: [number, number, number, number]) => r[0] < 4 || r[2] > W - 4 || r[1] < 4 || r[3] > H - 4 ||
    boxes.some(b => r[0] < b[2] && r[2] > b[0] && r[1] < b[3] && r[3] > b[1])
  return pts.map((p, i) => {
    const w = Math.max(54, labels[i].length * 6.6 + 24), h = 34
    const rects: Record<Side, [number, number, number, number]> = {
      above: [p.x - w / 2, p.y - 15 - h, p.x + w / 2, p.y - 15], below: [p.x - w / 2, p.y + 15, p.x + w / 2, p.y + 15 + h],
      right: [p.x + 14, p.y - h / 2, p.x + 14 + w, p.y + h / 2], left: [p.x - 14 - w, p.y - h / 2, p.x - 14, p.y + h / 2],
    }
    const order: Side[] = i % 2 ? ['below', 'above', 'right', 'left'] : ['above', 'below', 'right', 'left']
    const side = order.find(o => !hit(rects[o])) ?? order[0]
    boxes.push(rects[side])
    return side
  })
}

/** Flights arc upward; ground legs wind gently. */
function segment(a: XY, b: XY, arc: boolean, i: number, bulge = 1, wiggle = .16) {
  const dx = b.x - a.x, dy = b.y - a.y, len = Math.hypot(dx, dy) || 1
  let nx = -dy / len, ny = dx / len
  if (arc) {
    if (ny * bulge > 0) { nx = -nx; ny = -ny }
    const h = Math.min(len * .42, 96)
    return `Q ${a.x + dx / 2 + nx * h} ${a.y + dy / 2 + ny * h} ${b.x} ${b.y}`
  }
  const h = len * wiggle * (i % 2 ? 1 : -1)
  return `C ${a.x + dx / 3 + nx * h} ${a.y + dy / 3 + ny * h} ${a.x + 2 * dx / 3 - nx * h} ${a.y + 2 * dy / 3 - ny * h} ${b.x} ${b.y}`
}

export function RouteJourney({ stops, mode, suggested, options, activeDay, onPickDay, onMode, caption }: {
  stops: Stop[]; mode: TransportMode; suggested: TransportMode; options: TransportOption[]
  activeDay: number | null; onPickDay: (day: number | null) => void; onMode: (mode: TransportMode) => void; caption?: ReactNode
}) {
  const uid = useId().replace(/:/g, '')
  const pts = useMemo(() => layout(stops), [stops])
  const sides = useMemo(() => placeLabels(pts, stops.map(s => s.label)), [pts])
  const hasOrigin = stops[0]?.kind === 'origin'
  const legs: Leg[] = useMemo(() => pts.slice(1).map((b, i) => {
    const legMode: TransportMode = hasOrigin && i === 0 ? mode : 'local'
    return { a: pts[i], b, mode: legMode, seg: segment(pts[i], b, legMode === 'flight', i, 1, legMode === 'local' ? .09 : .16) }
  }), [pts, mode, hasOrigin])
  const fullD = pts.length ? `M ${pts[0].x} ${pts[0].y} ` + legs.map(l => l.seg).join(' ') : ''
  const last = pts[pts.length - 1]
  const returnD = hasOrigin && pts.length > 1 ? `M ${last.x} ${last.y} ` + segment(last, pts[0], true, 0, -1) : ''

  // Measure legs so the vehicle can park exactly on a day's stop.
  const fullRef = useRef<SVGPathElement>(null)
  const legRefs = useRef<(SVGPathElement | null)[]>([])
  const [metrics, setMetrics] = useState<{ total: number; cum: number[]; firstLeg: number } | null>(null)
  useLayoutEffect(() => {
    const lengths = legs.map((_, i) => legRefs.current[i]?.getTotalLength() ?? 0)
    const cum = lengths.reduce<number[]>((acc, l) => [...acc, acc[acc.length - 1] + l], [0])
    setMetrics({ total: Math.max(cum[cum.length - 1], 1), cum, firstLeg: hasOrigin ? lengths[0] ?? 0 : 0 })
  }, [fullD])

  const progress = useMotionValue(0)
  const vehicleRef = useRef<SVGGElement>(null), rotateRef = useRef<SVGGElement>(null)
  const [vehicle, setVehicle] = useState<TransportMode>(hasOrigin ? mode : 'local')
  function place(v: number) {
    const path = fullRef.current
    if (!path || !metrics || !vehicleRef.current) return
    const L = path.getTotalLength(), at = Math.max(0, Math.min(L, v * L))
    const p = path.getPointAtLength(at), ahead = path.getPointAtLength(Math.min(L, at + 2)), behind = path.getPointAtLength(Math.max(0, at - 2))
    vehicleRef.current.setAttribute('transform', `translate(${p.x} ${p.y})`)
    rotateRef.current?.setAttribute('transform', `rotate(${Math.atan2(ahead.y - behind.y, ahead.x - behind.x) * 180 / Math.PI})`)
    const kind: TransportMode = hasOrigin && at < metrics.firstLeg * (L / metrics.total) ? mode : 'local'
    setVehicle(prev => prev === kind ? prev : kind)
  }
  useMotionValueEvent(progress, 'change', place)

  const activeIndex = activeDay == null ? -1 : stops.findIndex(s => s.days.includes(activeDay))
  useEffect(() => {
    if (!metrics || pts.length < 2) return
    if (activeIndex < 0) {
      progress.jump(0); place(0)
      const run = animate(progress, 1, { duration: 2.8 + legs.length * 1.1, ease: [.45, 0, .55, 1], repeat: Infinity, repeatDelay: 1.6, delay: 1.2 })
      return () => run.stop()
    }
    const run = animate(progress, metrics.cum[activeIndex] / metrics.total, { duration: 1.5, ease: [.65, 0, .35, 1] })
    return () => run.stop()
  }, [metrics, activeIndex, mode])

  // Gentle parallax on the scenery.
  const px = useMotionValue(0), py = useMotionValue(0)
  const sx = useSpring(px, { stiffness: 60, damping: 18 }), sy = useSpring(py, { stiffness: 60, damping: 18 })
  const farX = useTransform(sx, v => v * -10), farY = useTransform(sy, v => v * -6)
  const nearX = useTransform(sx, v => v * 18), nearY = useTransform(sy, v => v * 10)
  function track(e: PointerEvent<HTMLElement>) {
    const r = e.currentTarget.getBoundingClientRect()
    px.set((e.clientX - r.left) / r.width - .5); py.set((e.clientY - r.top) / r.height - .5)
  }

  const available = [...travelModes.map(m => m.id), ...(options.some(o => o.mode === 'sea') ? ['sea' as const] : [])]
  const option = options.find(o => o.mode === mode)
  const draw = 1.4 + legs.length * .45

  return <div className="journey">
    <motion.div className="rj-stage" onPointerMove={track} onPointerLeave={() => { px.set(0); py.set(0) }}
      initial={{ opacity: 0, scale: .97 }} animate={{ opacity: 1, scale: 1 }} transition={{ duration: .7, ease }}>
      <motion.div className="sun" style={{ x: farX, y: farY }} />
      <motion.div className="cloud c1" style={{ x: farX, y: farY }} />
      <motion.div className="cloud c2" style={{ x: nearX, y: nearY }} />
      <div className="cloud c3" />
      <svg className="rj-birds" viewBox="0 0 60 20" aria-hidden><path d="M2 10 q5 -6 10 0 q5 -6 10 0 M30 6 q4 -5 8 0 q4 -5 8 0" /></svg>

      <svg viewBox={`0 0 ${W} ${H}`} className="rj-map" role="img" aria-label={'Route: ' + stops.map(s => s.label).join(' to ')}>
        <defs>
          <linearGradient id={uid + 'g'} x1="0" x2="1"><stop offset="0" stopColor="#2a7f7f" /><stop offset=".6" stopColor="#e07a4a" /><stop offset="1" stopColor="#d2603a" /></linearGradient>
          <mask id={uid + 'm'} maskUnits="userSpaceOnUse">
            <motion.path key={fullD} d={fullD} fill="none" stroke="#fff" strokeWidth="34" strokeLinecap="round" initial={{ pathLength: 0 }} animate={{ pathLength: 1 }} transition={{ duration: draw, ease: 'easeInOut', delay: .25 }} />
          </mask>
        </defs>
        {returnD && <motion.path d={returnD} className="rj-return" initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: draw + .3 }} />}
        <g mask={`url(#${uid}m)`}>
          {legs.map((leg, i) => {
            const d = `M ${leg.a.x} ${leg.a.y} ${leg.seg}`
            return <g key={i} className={'rj-leg ' + (leg.mode === 'local' ? 'road local' : leg.mode === 'car/taxi' || leg.mode === 'bus' ? 'road' : leg.mode)}>
              <path ref={el => { legRefs.current[i] = el }} d={d} className="rj-base" />
              <path d={d} className="rj-top" stroke={leg.mode === 'flight' || leg.mode === 'sea' ? `url(#${uid}g)` : undefined} />
            </g>
          })}
        </g>
        <motion.path ref={fullRef} d={fullD} className="rj-trail" stroke={`url(#${uid}g)`} style={{ pathLength: progress }} />

        {pts.map((p, i) => {
          const active = i === activeIndex, origin = stops[i].kind === 'origin'
          return <motion.g key={stops[i].name + i} initial={{ scale: 0, opacity: 0 }} animate={{ scale: 1, opacity: 1 }}
            transition={{ delay: .25 + draw * (pts.length > 1 ? i / (pts.length - 1) : 0), type: 'spring', stiffness: 380, damping: 18 }}
            style={{ transformBox: 'fill-box', transformOrigin: 'center' }} className="rj-pin" onClick={() => onPickDay(origin ? null : stops[i].days[0] ?? null)}>
            {(active || (activeIndex < 0 && (i === 0 || i === pts.length - 1))) && <circle cx={p.x} cy={p.y} r="7" className="pin-ring" />}
            <circle cx={p.x} cy={p.y} r={active ? 9 : 6.5} fill={origin ? '#2a7f7f' : active ? '#d2603a' : '#e88c5d'} stroke="#fffdf9" strokeWidth="3" style={{ transition: 'r .35s' }} />
          </motion.g>
        })}

        <g ref={vehicleRef} className="rj-vehicle" transform={pts[0] ? `translate(${pts[0].x} ${pts[0].y})` : undefined}>
          {vehicle === 'flight'
            ? <g ref={rotateRef}><g transform="scale(1.35)"><path d="M-12 0 L10 -1.5 Q14 0 10 1.5 Z M-2 0 L-7 -9 L-3 -9 L5 0 L-3 9 L-7 9 Z M-11 0 L-14 -5 L-12 -5 L-8 0 L-12 5 L-14 5 Z" fill="#14363b" /></g></g>
            : <g className="rj-badge"><circle r="15" /><g transform="translate(-9 -9)" color={vehicle === 'local' ? '#2a7f7f' : '#d2603a'}>{modeIcon(vehicle, 18)}</g></g>}
        </g>
      </svg>

      {pts.map((p, i) => {
        const stop = stops[i], side = sides[i] ?? 'above'
        const active = i === activeIndex
        const tag = stop.kind === 'origin' ? 'Start' : stop.days.length > 1 ? `Days ${stop.days[0]}–${stop.days[stop.days.length - 1]}` : stop.days.length ? `Day ${stop.days[0]}` : 'Stay'
        return <motion.button type="button" key={'chip' + stop.name + i} className={'rj-chip ' + side + (active ? ' on' : '')}
          style={{ left: `${p.x / W * 100}%`, top: `${p.y / H * 100}%` }} onClick={() => onPickDay(stop.kind === 'origin' ? null : stop.days[0] ?? null)}
          initial={{ opacity: 0, y: side === 'below' ? -6 : 6 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: .5 + draw * (pts.length > 1 ? i / (pts.length - 1) : 0), duration: .4, ease }}>
          <strong>{stop.label}</strong><span>{tag}</span>
        </motion.button>
      })}
      {caption && <div className="rj-caption">{caption}</div>}
    </motion.div>

    <div className="rj-modes" role="radiogroup" aria-label="Travel mode to your destination">
      {available.map(id => <button type="button" key={id} role="radio" aria-checked={mode === id} className="rj-mode" onClick={() => onMode(id)}>
        {mode === id && <motion.span layoutId={uid + 'pill'} className="rj-mode-pill" transition={{ type: 'spring', stiffness: 420, damping: 32 }} />}
        <span className="rj-mode-inner">{modeIcon(id, 15)}{modeLabel(id)}{suggested === id && <i>Suggested</i>}</span>
      </button>)}
    </div>
    <AnimatePresence mode="wait">
      <motion.div key={mode} className="rj-mode-info" initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -4 }} transition={{ duration: .25 }}>
        {option ? <><span>{option.route}</span><span className="rj-facts"><b>{option.duration_estimate}</b><b>{option.cost_estimate}</b></span><em>Planning estimate · {option.best_for}</em></>
          : <span>No {modeLabel(mode).toLowerCase()} estimate in this plan yet. Check services and timings before booking.</span>}
      </motion.div>
    </AnimatePresence>
  </div>
}
