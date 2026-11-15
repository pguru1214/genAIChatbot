import type { Evidence } from './components/ui'

export type Result = { answer: string; agent_trace: string[]; trip_id: string; planning_status?: 'scheduled' | 'needs_review'; connectivity?: { verification_links: { label: string; url: string }[] }; research?: { evidence: Evidence[]; errors: string[]; location?: { name?: string; admin1?: string; latitude?: number; longitude?: number } }; action?: { kind: string }; proposal_id?: string; food_stays?: FoodStays; schedule?: ScheduleDay[]; structured_plan?: StructuredPlan; request?: Details }
export type ServicePreferences = { transport_mode: 'unspecified' | 'car/taxi' | 'train' | 'bus' | 'flight'; departure_time: string | null; return_departure_time: string | null; dietary: 'any' | 'vegetarian' | 'vegan'; cuisine: string; accessibility: boolean; stay_preference: 'any' | 'hotel' | 'guest_house' | 'hostel' | 'apartment' }
export type PlaceReference = { id: string; name: string; address: string; type: string; distance_m: number; url: string; website?: string | null; phone?: string | null; opening_hours?: string | null; cuisine?: string | null; amenities: string[]; quality_note: string; reason: string; retrieved_at: string; arrival?: string; detour_minutes?: number }
export type MealReference = { meal: string; start: string; end: string; location: string; places: PlaceReference[]; status: string; notice?: string | null; search_url: string; selected_place_id?: string }
export type ServiceDay = { day: number; date: string; base: string; meals: MealReference[]; destination_stays: PlaceReference[]; stay_notice?: string | null; stay_search_url: string; overnight: { status: string; reason?: string; places: PlaceReference[] }; journey?: { origin: string; destination: string; departure: string; arrival: string; distance_km: number; duration_minutes: number; timing_basis: string; route_url: string }; return_notice?: string; return_journey?: ServiceDay }
export type FoodStays = { preferences: ServicePreferences; days: ServiceDay[]; notice?: string | null; limitations: string; retrieved_at: string; provider: string }
export type Details = Record<string, string | number>
export type Trip = { id: string; destination: string; answer: string; mode: string }
export type ConversationSummary = { id: string; title: string }
export type Conversation = {
  id: string; details: Details; messages: { role: string; content: string }[]
  pending: { field: string; question: string; choices?: string[] } | null
  checkpoint_id: string | null; recoverable: boolean; result?: Result | null
}
/** Whatever the trip panel is currently showing. */
export type Plan = { key: string; source: 'chat' | 'quick' | 'saved'; destination: string; days: number; answer: string; result: Result | null; details?: Details; streaming?: boolean; status?: string }
export type ActivityKind = 'visit' | 'transfer' | 'meal' | 'break' | 'check-in'
export type Activity = { kind: ActivityKind; title: string; duration_minutes: number; description: string; source_ids?: string[]; start?: string; end?: string; next_attraction?: string | null }
export type DayWeather = { date: string; location: string; available: boolean; min_c?: number | null; max_c?: number | null; rain_probability?: number | null; reason?: string }
export type ScheduleDay = { day: number; date: string; base: string; status: 'scheduled' | 'needs_review'; review_note?: string; activities: Activity[]; unscheduled_options?: Activity[]; weather?: DayWeather }
export type TransportMode = 'train' | 'bus' | 'car/taxi' | 'flight' | 'sea' | 'local'
export type TransportOption = { mode: TransportMode; route: string; duration_estimate: string; cost_estimate: string; best_for: string }
export type StructuredPlan = { overview: string; recommended_mode: string; transport_options: TransportOption[]; days: { day: number; base: string; activities: Activity[]; review_note?: string | null }[]; budget_allocation: { category: string; amount: number }[]; packing_list: string[]; notes: string[]; travel_legs: { day: number; title: string; duration_minutes: number; timing_note: string }[] }
