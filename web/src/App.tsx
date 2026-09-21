import { useCallback, useEffect, useState } from 'react'
import ChatPanel, { type ChatMessage } from './components/ChatPanel'
import ReportView from './components/ReportView'
import SessionList from './components/SessionList'
import { createSession, getSession, listSessions, streamRun } from './lib/api'
import type { RunUsage, Session } from './types'

export default function App() {
  const [sessions, setSessions] = useState<Session[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)

  // Live run state
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [steps, setSteps] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const [report, setReport] = useState<string | null>(null)
  const [status, setStatus] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [abort, setAbort] = useState<AbortController | null>(null)
  const [usage, setUsage] = useState<RunUsage | null>(null)

  const refreshSessions = useCallback(async () => {
    try {
      const { items } = await listSessions()
      setSessions(items)
    } catch (e) {
      setError(`无法加载会话列表：${String(e)}（后端是否已启动？）`)
    }
  }, [])

  useEffect(() => {
    refreshSessions()
  }, [refreshSessions])

  async function openSession(id: string) {
    setSelectedId(id)
    setError(null)
    setReport(null)
    setSteps([])
    setBusy(false)
    try {
      const detail = await getSession(id)
      setStatus(detail.status)
      setReport(detail.final_report)
      setMessages(
        detail.messages.map((m) => ({ role: m.role, content: m.content })),
      )
    } catch (e) {
      setError(`加载会话失败：${String(e)}`)
    }
  }

  async function runStream(sessionId: string, message?: string) {
    const controller = new AbortController()
    setAbort(controller)
    setBusy(true)
    setError(null)
    setSteps([])
    setUsage(null)
    try {
      for await (const ev of streamRun(sessionId, message, controller.signal)) {
        if (ev.event === 'node') {
          setSteps((s) => [...s, ev.node])
        } else if (ev.event === 'message') {
          const isReport = ev.node === 'final_report_generation'
          setMessages((msgs) => {
            const last = msgs[msgs.length - 1]
            // Append streaming text to the last assistant bubble of the same
            // phase; open a new bubble when the phase changes.
            if (last && last.role === 'assistant' && last.streamKey === ev.node) {
              return [
                ...msgs.slice(0, -1),
                { role: 'assistant', content: last.content + ev.content, streamKey: ev.node },
              ]
            }
            return [
              ...msgs,
              {
                role: 'assistant',
                content: isReport ? ev.content : ev.content,
                streamKey: ev.node,
              },
            ]
          })
        } else if (ev.event === 'done') {
          setStatus(ev.status)
          if (ev.final_report) setReport(ev.final_report)
          if (ev.usage) setUsage(ev.usage)
          refreshSessions()
        } else if (ev.event === 'error') {
          setError(ev.message)
          refreshSessions()
        }
      }
    } catch (e) {
      // A user-initiated stop is not an error: the server archives `cancelled`.
      if ((e as Error)?.name === 'AbortError') {
        setStatus('cancelled')
      } else {
        setError(`流式连接中断：${String(e)}`)
      }
      refreshSessions()
    } finally {
      setAbort(null)
      setBusy(false)
    }
  }

  async function onSend(text: string) {
    setError(null)
    setMessages((msgs) => [...msgs, { role: 'user', content: text }])

    if (selectedId && (status === 'awaiting_input' || status === 'created')) {
      // Follow-up (e.g. answering a clarification) on the existing thread.
      await runStream(selectedId, text)
      return
    }

    try {
      const session = await createSession(text)
      setSelectedId(session.id)
      setStatus(session.status)
      setSessions((s) => [session, ...s])
      await runStream(session.id)
    } catch (e) {
      setError(`创建会话失败：${String(e)}`)
      setBusy(false)
    }
  }

  return (
    <div className="layout">
      <SessionList
        sessions={sessions}
        selectedId={selectedId}
        onSelect={openSession}
        onRefresh={refreshSessions}
      />
      <main className="main">
        <header>
          <h1>Open Deep Research</h1>
          <span className={`status-badge status-${status ?? ''}`}>
            {status ?? '就绪'}
          </span>
        </header>
        {error && <p className="error">{error}</p>}
        {usage && Object.keys(usage).length > 0 && (
          <p className="usage">本次 token 合计：{Object.values(usage).reduce((sum, u) => sum + u.total, 0)}</p>
        )}
        <ChatPanel
          messages={messages}
          steps={steps}
          busy={busy}
          onSend={onSend}
          onStop={() => abort?.abort()}
        />
        {report && (
          <section className="report-pane">
            <h2>最终报告</h2>
            <ReportView report={report} />
          </section>
        )}
      </main>
    </div>
  )
}
