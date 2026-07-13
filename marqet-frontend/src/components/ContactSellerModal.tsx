import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { apiContactSeller } from '../api'
import { useToast } from './Toast'

const css = `
.cs-overlay { position:fixed;inset:0;background:rgba(15,15,35,.6);backdrop-filter:blur(4px);z-index:1000;display:flex;align-items:center;justify-content:center;padding:16px; }
.cs-box { background:#fff;border-radius:18px;padding:28px 24px 22px;width:100%;max-width:420px;box-shadow:0 20px 60px rgba(0,0,0,.18);position:relative; }
.cs-close { position:absolute;top:14px;right:14px;width:28px;height:28px;border-radius:50%;border:none;background:none;cursor:pointer;color:#94A3B8;display:flex;align-items:center;justify-content:center; }
.cs-close:hover { background:#F1F5F9;color:#475569; }
.cs-title { font-size:18px;font-weight:800;color:#1E1B4B;margin-bottom:4px; }
.cs-sub { font-size:13px;color:#64748B;margin-bottom:16px; }
.cs-prod { background:#F8FAFC;border-radius:10px;padding:10px 12px;font-size:13px;color:#475569;margin-bottom:14px;border:1px solid #E2E8F0; }
.cs-prod strong { color:#1E1B4B; }
.cs-ta { width:100%;border:1.5px solid #E2E8F0;border-radius:12px;padding:11px 13px;font-size:14px;font-family:inherit;resize:vertical;outline:none;min-height:90px;transition:border-color .2s;background:#FAFAFA;box-sizing:border-box; }
.cs-ta:focus { border-color:#5B4FE8;background:#fff; }
.cs-btn { width:100%;height:46px;border-radius:12px;background:linear-gradient(135deg,#5B4FE8,#3B82F6);color:#fff;font-size:15px;font-weight:700;border:none;cursor:pointer;transition:opacity .2s;margin-top:12px; }
.cs-btn:hover:not(:disabled) { opacity:.9; }
.cs-btn:disabled { opacity:.5; }
.cs-err { background:#FEF2F2;border:1px solid #FCA5A5;border-radius:8px;padding:8px 12px;font-size:13px;color:#DC2626;margin-bottom:10px; }
`

interface Props {
  itemId: number
  productName: string
  sellerName: string
  onClose: () => void
}

export default function ContactSellerModal({ itemId, productName, sellerName, onClose }: Props) {
  const [msg, setMsg] = useState('')
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState('')
  const { show: toast } = useToast()
  const nav = useNavigate()

  async function send() {
    if (!msg.trim()) return
    setErr('')
    setLoading(true)
    try {
      const res = await apiContactSeller(itemId, msg.trim())
      toast('Сообщение отправлено!', 'success')
      onClose()
      nav(`/messages/${res.id}`)
    } catch (e: any) {
      const m = e?.message || ''
      if (m.includes('открытый запрос')) {
        // Already existing inquiry — just navigate to messages
        toast('Уже есть активный запрос по этому товару', 'info')
        onClose()
        nav('/messages')
      } else {
        setErr(m || 'Ошибка отправки')
      }
    } finally {
      setLoading(false)
    }
  }

  return (
    <>
      <style>{css}</style>
      <div className="cs-overlay" onClick={onClose}>
        <div className="cs-box" onClick={e => e.stopPropagation()}>
          <button className="cs-close" onClick={onClose}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path d="M18 6 6 18M6 6l12 12"/></svg>
          </button>
          <div className="cs-title">Написать продавцу</div>
          <div className="cs-sub">Задайте вопрос или уточните условия</div>
          <div className="cs-prod">
            Товар: <strong>{productName}</strong><br />
            Продавец: <strong>{sellerName}</strong>
          </div>
          {err && <div className="cs-err">{err}</div>}
          <textarea
            className="cs-ta"
            placeholder="Здравствуйте, меня интересует этот товар..."
            value={msg}
            onChange={e => setMsg(e.target.value)}
            autoFocus
          />
          <button className="cs-btn" onClick={send} disabled={!msg.trim() || loading}>
            {loading ? 'Отправка...' : 'Отправить'}
          </button>
        </div>
      </div>
    </>
  )
}
