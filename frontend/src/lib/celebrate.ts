import confetti from 'canvas-confetti'

const colors = ['#d2603a', '#f2a65a', '#e0b25c', '#2a7f7f', '#fffdf9']
const seen = new Set<string>()

/** A short burst of confetti the first time a plan arrives in this session. */
export function celebrate(key: string) {
  if (seen.has(key)) return
  seen.add(key)
  if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) return
  const burst = (x: number, angle: number) => confetti({ particleCount: 70, spread: 62, startVelocity: 48, angle, origin: { x, y: .75 }, colors, scalar: .9, ticks: 220, zIndex: 70, disableForReducedMotion: true })
  burst(.25, 60); setTimeout(() => burst(.75, 120), 160)
}
