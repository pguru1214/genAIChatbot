import { useEffect, useState } from 'react'
import type { Details, Plan, ScheduleDay, TransportMode } from '../types'

export type Point = { lat: number; lon: number }
export type Stop = { name: string; label: string; kind: 'origin' | 'base'; days: number[]; point?: Point | null }

const same = (a: string, b: string) => a.trim().toLowerCase() === b.trim().toLowerCase()
export const shortName = (place: string) => place.split(',')[0].replace(/\s*\([^)]*\)/g, '').trim().slice(0, 26) || place.slice(0, 26)

/** Details used for this plan, regardless of where it came from. */
export function planDetails(plan: Plan | null, fallback: Details): Details {
  return plan?.details ?? plan?.result?.request ?? fallback
}

/** Day schedule: structured if present, else derived from the structured plan. */
export function planDays(plan: Plan | null): ScheduleDay[] {
  const result = plan?.result
  if (result?.schedule?.length) return result.schedule
  return (result?.structured_plan?.days ?? []).map(d => ({
    day: d.day, date: '', base: d.base, status: d.review_note ? 'needs_review' : 'scheduled',
    review_note: d.review_note ?? undefined, activities: d.review_note ? [] : d.activities, unscheduled_options: d.review_note ? d.activities : [],
  }))
}

/** Route stops: the starting city, then each day's base (consecutive days at one base are merged). */
export function tripStops(plan: Plan | null, details: Details): Stop[] {
  const stops: Stop[] = []
  const origin = String(details.origin ?? '').trim()
  if (origin) stops.push({ name: origin, label: shortName(origin), kind: 'origin', days: [] })
  for (const day of planDays(plan)) {
    const last = stops[stops.length - 1]
    if (last?.kind === 'base' && same(last.name, day.base)) last.days.push(day.day)
    else stops.push({ name: day.base, label: shortName(day.base), kind: 'base', days: [day.day] })
  }
  if (!stops.some(s => s.kind === 'base') && plan?.destination) stops.push({ name: plan.destination, label: shortName(plan.destination), kind: 'base', days: [] })
  return stops
}

export const travelModes: { id: TransportMode; label: string }[] = [
  { id: 'flight', label: 'Flight' }, { id: 'train', label: 'Train' }, { id: 'bus', label: 'Bus' }, { id: 'car/taxi', label: 'Car' },
]
const keywords: [TransportMode, RegExp][] = [
  ['flight', /\b(flight|fly|flying|air(port|line)?)\b/], ['train', /\b(train|rail|railway)\b/], ['bus', /\bbus(es)?\b/],
  ['car/taxi', /\b(car|cab|taxi|drive|driving|road ?trip)\b/], ['sea', /\b(ferry|ship|sea|boat)\b/],
]

/** The mode the planner suggested: an explicit preference, else the earliest mode named in the recommendation. */
export function suggestedMode(plan: Plan | null, preferChosen = true): TransportMode {
  const chosen = plan?.result?.food_stays?.preferences.transport_mode
  if (preferChosen && chosen && chosen !== 'unspecified') return chosen
  const text = plan?.result?.structured_plan?.recommended_mode.toLowerCase() ?? ''
  const hits = keywords.map(([mode, re]) => [mode, text.search(re)] as const).filter(([, i]) => i >= 0).sort((a, b) => a[1] - b[1])
  if (hits.length) return hits[0][0]
  const first = plan?.result?.structured_plan?.transport_options.find(o => o.mode !== 'local')?.mode
  return first ?? 'car/taxi'
}

/** Best-effort coordinates for the route drawing. Missing points fall back to a schematic layout. */
export function useGeocodedStops(stops: Stop[], region: string, destination?: Point | null): Stop[] {
  const key = stops.map(s => s.name).join('|') + '#' + region + '#' + (destination ? destination.lat + ',' + destination.lon : '')
  const [points, setPoints] = useState<{ key: string; points: (Point | null)[] }>({ key: '', points: [] })
  useEffect(() => {
    if (!stops.length) return
    const controller = new AbortController()
    // Day bases are disambiguated by the destination region and coordinates; the origin can be anywhere in India.
    const places = stops.slice(0, 10).map(s => s.kind === 'origin' ? { name: s.name }
      : { name: s.name, region, near: destination ? [destination.lat, destination.lon] : null })
    fetch('/api/geocode', { method: 'POST', headers: { 'Content-Type': 'application/json' }, signal: controller.signal,
      body: JSON.stringify({ places }) })
      .then(r => r.ok ? r.json() : { points: [] })
      .then(data => setPoints({ key, points: data.points ?? [] }))
      .catch(() => { /* The schematic route still renders. */ })
    return () => controller.abort()
  }, [key])
  const resolved = points.key === key ? points.points : []
  let usedDestination = false
  return stops.map((stop, i) => {
    let point = resolved[i] ?? null
    if (!point && stop.kind === 'base' && destination && !usedDestination) { point = destination; usedDestination = true }
    return { ...stop, point }
  })
}

export const formatDate = (iso: string, opts: Intl.DateTimeFormatOptions = { weekday: 'short', day: 'numeric', month: 'short' }) => {
  if (!iso) return ''
  const d = new Date(iso + 'T00:00:00')
  return isNaN(d.getTime()) ? iso : d.toLocaleDateString('en-IN', opts)
}
export const minutes = (m: number) => m >= 60 ? `${Math.floor(m / 60)}h${m % 60 ? ` ${m % 60}m` : ''}` : `${m}m`
