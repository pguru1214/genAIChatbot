import type { Evidence } from './components/ui'

export type Result = { answer: string; agent_trace: string[]; trip_id: string; planning_status?: 'scheduled' | 'needs_review'; connectivity?: { verification_links: { label: string; url: string }[] }; research?: { evidence: Evidence[]; errors: string[] }; action?: { kind: string }; proposal_id?: string }
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
