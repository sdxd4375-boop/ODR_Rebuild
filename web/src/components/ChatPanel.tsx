import { useEffect, useRef, useState } from 'react'

export interface ChatMessage {
  role: 'user' | 'assistant' | 'system'
  content: string
  /** Streaming phase the text belongs to (e.g. the graph node name). */
  streamKey?: string
}

/**
 * Conversation pane: message history, live progress timeline while a run is
 * streaming, and the question/follow-up input.
 */
export default function ChatPanel({
  messages,
  steps,
  busy,
  onSend,
}: {
  messages: ChatMessage[]
  steps: string[]
  busy: boolean
  onSend: (text: string) => void
}) {
  const [input, setInput] = useState('')
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, steps])

  function submit() {
    const text = input.trim()
    if (!text || busy) return
    setInput('')
    onSend(text)
  }

  return (
    <section className="chat">
      <div className="chat-scroll">
        {messages.map((m, i) =>
          m.role === 'system' ? (
            <p key={i} className="system-note">
              {m.content}
            </p>
          ) : (
            <div key={i} className={`bubble ${m.role}`}>
              {m.content}
            </div>
          ),
        )}

        {busy && (
          <div className="progress">
            {steps.slice(-8).map((s, i) => (
              <div key={i} className="step">
                {s}
              </div>
            ))}
            <div className="step active">研究中…</div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      <div className="chat-input">
        <textarea
          rows={2}
          value={input}
          placeholder={
            busy
              ? '研究进行中…'
              : '输入你的研究问题（或补充澄清信息）……'
          }
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              submit()
            }
          }}
        />
        <button onClick={submit} disabled={busy || !input.trim()}>
          {busy ? '研究中…' : '发送'}
        </button>
      </div>
    </section>
  )
}
