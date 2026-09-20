// Types mirroring src/server/routers/sessions.py response models.

export type SessionStatus =
  | 'created'
  | 'running'
  | 'awaiting_input'
  | 'completed'
  | 'failed'

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

// SSE events emitted by POST /api/sessions/{id}/runs/stream
export type StreamEvent =
  | { event: 'node'; node: string }
  | { event: 'message'; node: string; content: string }
  | { event: 'done'; status: SessionStatus; final_report: string | null }
  | { event: 'error'; message: string }
