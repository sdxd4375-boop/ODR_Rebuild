// Types mirroring src/server/routers/sessions.py response models.

export type SessionStatus =
  | 'created'
  | 'running'
  | 'awaiting_input'
  | 'completed'
  | 'failed'
  | 'cancelled'

export interface Session {
  id: string
  question: string
  status: SessionStatus
  research_brief: string | null
  final_report: string | null
  error_message: string | null
  created_at: string
  finished_at: string | null
}

export interface SessionDetail extends Session {
  messages: { role: 'user' | 'assistant'; content: string }[]
}

/** Token usage per graph node, as aggregated by the server on completion. */
export interface NodeUsage {
  input: number
  output: number
  total: number
  calls: number
  model?: string | null
}

export type RunUsage = Record<string, NodeUsage>

// SSE events emitted by POST /api/sessions/{id}/runs/stream
export type StreamEvent =
  | { event: 'node'; node: string; subgraph?: boolean; namespace?: string }
  | { event: 'message'; node: string; content: string; subgraph?: boolean; namespace?: string }
  | { event: 'done'; status: SessionStatus; final_report: string | null; usage?: RunUsage }
  | { event: 'error'; message: string }
