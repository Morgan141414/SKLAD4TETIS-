import { useEffect, useState, useRef } from 'react'
import { useParams, Link, useNavigate } from 'react-router-dom'
import { useStore } from '../store'
import { apiGetMyInquiries, apiGetInquiryMessages, apiSendInquiryMessage } from '../api'
import { useToast } from '../components/Toast'

const css = `
.msg-page { max-width:1100px; margin:0 auto; padding:24px 20px 60px; display:grid; grid-template-columns:300px 1fr; gap:18px; min-height:calc(100vh - 64px); }
@media(max-width:760px) { .msg-page { grid-template-columns:1fr; } .msg-thread-panel { display:none; } .msg-page.in-thread .msg-list-panel { display:none; } .msg-page.in-thread .msg-thread-panel { display:flex; } }
.msg-list-panel { background:#fff; border-radius:16px; border:1px solid #E2E8F0; overflow:hidden; display:flex; flex-direction:column; height:calc(100vh - 120px); }
.msg-list-header { padding:14px 16px; border-bottom:1px solid #F1F5F9; }
.msg-list-header h2 { font-size:15px; font-weight:800; color:#1E1B4B; }
.msg-list-empty { padding:40px 16px; text-align:center; color:#94A3B8; font-size:14px; }
.inq-item { padding:12px 14px; border-bottom:1px solid #F1F5F9; cursor:pointer; transition:background .15s; }
.inq-item:hover { background:#F8FAFC; }
.inq-item.active { background:#EEF2FF; }
.inq-prod { font-size:13px; font-weight:700; color:#1E1B4B; margin-bottom:2px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.inq-seller { font-size:11px; color:#94A3B8; margin-bottom:3px; }
.inq-last { font-size:12px; color:#64748B; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.inq-status { display:inline-block; font-size:10px; font-weight:700; padding:2px 6px; border-radius:6px; margin-left:6px; }
.status-pending { background:#FEF3C7; color:#D97706; }
.status-responded { background:#D1FAE5; color:#065F46; }
.status-closed { background:#F1F5F9; color:#94A3B8; }
.msg-thread-panel { background:#fff; border-radius:16px; border:1px solid #E2E8F0; display:flex; flex-direction:column; height:calc(100vh - 120px); overflow:hidden; }
.thread-header { padding:14px 18px; border-bottom:1px solid #F1F5F9; }
.thread-prod { font-size:15px; font-weight:800; color:#1E1B4B; }
.thread-seller { font-size:13px; color:#64748B; margin-top:2px; }
.thread-back { color:#5B4FE8; font-size:13px; font-weight:600; display:none; }
@media(max-width:760px) { .thread-back { display:inline; } }
.thread-msgs { flex:1; overflow-y:auto; padding:14px 16px; display:flex; flex-direction:column; gap:8px; }
.msg-bubble { max-width:72%; padding:10px 14px; border-radius:16px; font-size:14px; line-height:1.5; }
.msg-bubble.buyer { background:#EEF2FF; color:#1E1B4B; border-bottom-left-radius:4px; align-self:flex-start; }
.msg-bubble.supplier { background:linear-gradient(135deg,#5B4FE8,#3B82F6); color:#fff; border-bottom-right-radius:4px; align-self:flex-end; }
.msg-time { font-size:10px; opacity:.6; margin-top:3px; }
.thread-input { padding:12px 14px; border-top:1px solid #F1F5F9; display:flex; gap:8px; }
.thread-input textarea { flex:1; border:1.5px solid #E2E8F0; border-radius:12px; padding:9px 12px; font-size:14px; font-family:inherit; resize:none; outline:none; min-height:40px; max-height:100px; transition:border-color .2s; }
.thread-input textarea:focus { border-color:#5B4FE8; }
.thread-send { width:44px; height:44px; border-radius:12px; background:var(--brand-grad); border:none; color:#fff; display:flex; align-items:center; justify-content:center; flex-shrink:0; transition:opacity .2s; }
.thread-send:hover:not(:disabled) { opacity:.85; }
.thread-send:disabled { opacity:.4; }
.thread-empty { flex:1; display:flex; align-items:center; justify-content:center; flex-direction:column; gap:8px; color:#94A3B8; }
.thread-placeholder { flex:1; display:flex; align-items:center; justify-content:center; color:#CBD5E1; font-size:14px; }
.spinner-sm { width:24px; height:24px; border:2px solid #E2E8F0; border-top-color:#5B4FE8; border-radius:50%; animation:spin .7s linear infinite; margin:20px auto; }
@keyframes spin { to{transform:rotate(360deg)} }
`

function fmtTime(iso: string) {
  const d = new Date(iso)
  const now = new Date()
  if (d.toDateString() === now.toDateString()) return d.toLocaleTimeString('ru', { hour: '2-digit', minute: '2-digit' })
  return d.toLocaleDateString('ru', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
}

function statusLabel(status: string) {
  const map: Record<string, string> = { pending: 'Ожидание', responded: 'Ответили', ordered: 'Заказан', closed: 'Закрыт', cancelled: 'Отменён' }
  return map[status] || status
}

function statusCls(status: string) {
  if (status === 'responded') return 'status-responded'
  if (status === 'closed' || status === 'cancelled') return 'status-closed'
  return 'status-pending'
}

export default function MessagesPage() {
  const { id } = useParams<{ id?: string }>()
  const nav = useNavigate()
  const { user, token } = useStore()
  const { show: toast } = useToast()

  const [inquiries, setInquiries] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const [messages, setMessages] = useState<any[]>([])
  const [msgLoading, setMsgLoading] = useState(false)
  const [text, setText] = useState('')
  const [sending, setSending] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const activeInquiry = inquiries.find(i => String(i.id) === id)

  useEffect(() => {
    if (!token) { nav('/'); return }
    apiGetMyInquiries()
      .then(r => setInquiries(r.items || []))
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [token])

  useEffect(() => {
    if (!id) { setMessages([]); return }
    loadMessages()
    pollRef.current = setInterval(loadMessages, 5000)
    return () => { if (pollRef.current) clearInterval(pollRef.current) }
  }, [id])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  async function loadMessages() {
    if (!id) return
    try {
      const msgs = await apiGetInquiryMessages(Number(id))
      setMessages(msgs)
    } catch {}
  }

  async function send() {
    if (!text.trim() || !id) return
    setSending(true)
    try {
      await apiSendInquiryMessage(Number(id), text.trim())
      setText('')
      await loadMessages()
    } catch (e: any) {
      toast(e?.message || 'Ошибка отправки', 'error')
    } finally {
      setSending(false)
    }
  }

  function handleKey(e: React.KeyboardEvent) {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() }
  }

  if (!token) return null

  return (
    <>
      <style>{css}</style>
      <div className={`msg-page${id ? ' in-thread' : ''}`}>
        {/* Left: Inquiry List */}
        <div className="msg-list-panel">
          <div className="msg-list-header">
            <h2>Мои сообщения</h2>
          </div>
          {loading ? (
            <div className="spinner-sm" />
          ) : inquiries.length === 0 ? (
            <div className="msg-list-empty">
              Нет сообщений.<br />
              <Link to="/" style={{ color: '#5B4FE8', fontWeight: 600, fontSize: 13, marginTop: 8, display: 'inline-block' }}>Перейти в каталог →</Link>
            </div>
          ) : (
            inquiries.map(inq => (
              <div
                key={inq.id}
                className={`inq-item ${String(inq.id) === id ? 'active' : ''}`}
                onClick={() => nav(`/messages/${inq.id}`)}
              >
                <div className="inq-prod">
                  {inq.product_name}
                  <span className={`inq-status ${statusCls(inq.status)}`}>{statusLabel(inq.status)}</span>
                </div>
                <div className="inq-seller">{inq.supplier_name}</div>
                <div className="inq-last">{inq.notes || 'Запрос отправлен'}</div>
              </div>
            ))
          )}
        </div>

        {/* Right: Thread */}
        <div className="msg-thread-panel">
          {!id ? (
            <div className="thread-placeholder">Выберите диалог</div>
          ) : (
            <>
              <div className="thread-header">
                <button className="thread-back" onClick={() => nav('/messages')} style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 0, marginBottom: 8 }}>
                  ← Назад
                </button>
                <div className="thread-prod">{activeInquiry?.product_name || 'Товар'}</div>
                <div className="thread-seller">
                  {activeInquiry?.supplier_name
                    ? <Link to={`/product/${activeInquiry?.catalog_item_id}`} style={{ color: '#5B4FE8' }}>{activeInquiry.supplier_name}</Link>
                    : 'Продавец'}
                </div>
              </div>
              <div className="thread-msgs">
                {msgLoading && <div className="spinner-sm" />}
                {messages.length === 0 && !msgLoading && (
                  <div className="thread-empty">
                    <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="#CBD5E1" strokeWidth="1.5"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
                    <span>Нет сообщений</span>
                  </div>
                )}
                {messages.map(msg => (
                  <div key={msg.id} style={{ display: 'flex', flexDirection: 'column', alignItems: msg.role === 'buyer' ? 'flex-start' : 'flex-end' }}>
                    <div className={`msg-bubble ${msg.role}`}>
                      {msg.body}
                      <div className="msg-time">{fmtTime(msg.created_at)}</div>
                    </div>
                  </div>
                ))}
                <div ref={bottomRef} />
              </div>
              <div className="thread-input">
                <textarea
                  placeholder="Написать сообщение... (Enter — отправить)"
                  value={text}
                  onChange={e => setText(e.target.value)}
                  onKeyDown={handleKey}
                  rows={1}
                />
                <button className="thread-send" onClick={send} disabled={!text.trim() || sending}>
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path d="m22 2-7 20-4-9-9-4 20-7z"/></svg>
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </>
  )
}
