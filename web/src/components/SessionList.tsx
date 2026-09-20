import type { Session } from '../types'

const STATUS_LABEL: Record<string, string> = {
  created: '已创建',
  running: '研究中',
  awaiting_input: '等待补充信息',
  completed: '已完成',
  failed: '失败',
}

export default function SessionList({
  sessions,
  selectedId,
  onSelect,
  onRefresh,
}: {
  sessions: Session[]
  selectedId: string | null
  onSelect: (id: string) => void
  onRefresh: () => void
}) {
  return (
    <aside className="sidebar">
      <div className="sidebar-header">
        <h2>研究历史</h2>
        <button onClick={onRefresh} title="刷新列表">
          刷新
        </button>
      </div>
      {sessions.length === 0 && <p className="empty">暂无会话</p>}
      <ul>
        {sessions.map((s) => (
          <li
            key={s.id}
            className={s.id === selectedId ? 'selected' : ''}
            onClick={() => onSelect(s.id)}
          >
            <span className="question">{s.question}</span>
            <span className={`status status-${s.status}`}>
              {STATUS_LABEL[s.status] ?? s.status}
            </span>
          </li>
        ))}
      </ul>
    </aside>
  )
}
