import { useState } from 'react'
import { useStore } from '../store'

const css = `
.sw-fab { position:fixed; bottom:28px; right:28px; z-index:1000; }
.sw-btn { width:56px; height:56px; border-radius:50%; background:var(--brand-grad); color:#fff; border:none; box-shadow:0 4px 20px rgba(91,79,232,.4); display:flex; align-items:center; justify-content:center; transition:all .2s; }
.sw-btn:hover { transform:scale(1.08); box-shadow:0 6px 28px rgba(91,79,232,.5); }
.sw-btn.open { background:linear-gradient(135deg,#EF4444,#DC2626); box-shadow:0 4px 20px rgba(239,68,68,.4); }
.sw-panel { position:fixed; bottom:96px; right:28px; width:340px; background:#fff; border-radius:20px; box-shadow:0 16px 48px rgba(0,0,0,.16); z-index:1000; overflow:hidden; animation:sw-in .2s ease; }
@keyframes sw-in { from{opacity:0;transform:scale(.95) translateY(8px)} to{opacity:1;transform:none} }
.sw-head { background:var(--brand-grad); padding:20px 20px 16px; color:#fff; }
.sw-head h3 { font-size:16px; font-weight:800; margin-bottom:4px; }
.sw-head p { font-size:13px; opacity:.85; }
.sw-body { padding:16px; }
.sw-field { margin-bottom:12px; }
.sw-label { font-size:12px; font-weight:600; color:#475569; margin-bottom:5px; display:block; }
.sw-input { width:100%; height:40px; padding:0 12px; border:1.5px solid #E2E8F0; border-radius:10px; font-size:14px; font-family:inherit; outline:none; transition:border-color .18s; }
.sw-input:focus { border-color:#5B4FE8; }
.sw-textarea { width:100%; padding:10px 12px; border:1.5px solid #E2E8F0; border-radius:10px; font-size:14px; font-family:inherit; outline:none; resize:none; transition:border-color .18s; min-height:90px; }
.sw-textarea:focus { border-color:#5B4FE8; }
.sw-err { font-size:12px; color:#EF4444; margin-bottom:10px; }
.sw-submit { width:100%; height:44px; border-radius:12px; background:var(--brand-grad); color:#fff; font-size:14px; font-weight:700; border:none; transition:opacity .18s; }
.sw-submit:hover:not(:disabled) { opacity:.9; }
.sw-submit:disabled { opacity:.5; }
.sw-success { text-align:center; padding:24px 16px; }
.sw-success-ico { width:48px; height:48px; border-radius:50%; background:#D1FAE5; display:flex; align-items:center; justify-content:center; margin:0 auto 12px; }
.sw-success h4 { font-size:16px; font-weight:800; color:#1E1B4B; margin-bottom:6px; }
.sw-success p { font-size:13px; color:#64748B; line-height:1.5; }
@media(max-width:400px) { .sw-panel{right:8px;width:calc(100vw - 16px)} .sw-fab{right:16px} }
`

interface TicketForm {
  name: string
  email: string
  phone: string
  subject: string
  message: string
}

export default function SupportWidget() {
  const { user } = useStore()
  const [open, setOpen] = useState(false)
  const [sent, setSent] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [form, setForm] = useState<TicketForm>({
    name: user?.name || '',
    email: user?.email || '',
    phone: '',
    subject: '',
    message: '',
  })

  function set(k: keyof TicketForm, v: string) {
    setForm(f => ({ ...f, [k]: v }))
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    if (!form.name.trim() || !form.subject.trim() || !form.message.trim()) {
      setError('Заполните обязательные поля')
      return
    }
    setLoading(true)
    try {
      const res = await fetch('/api/v1/marketplace/support', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: form.name.trim(),
          email: form.email.trim() || null,
          phone: form.phone.trim() || null,
          subject: form.subject.trim(),
          message: form.message.trim(),
        }),
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        throw new Error(err?.detail?.message ?? 'Ошибка отправки')
      }
      setSent(true)
    } catch (e: any) {
      setError(e.message || 'Не удалось отправить обращение')
    } finally {
      setLoading(false)
    }
  }

  function handleOpen() {
    if (open) { setOpen(false); return }
    setSent(false)
    setError('')
    setForm({ name: user?.name || '', email: user?.email || '', phone: '', subject: '', message: '' })
    setOpen(true)
  }

  return (
    <>
      <style>{css}</style>
      <div className="sw-fab">
        {open && (
          <div className="sw-panel">
            <div className="sw-head">
              <h3>Служба поддержки</h3>
              <p>Ответим в течение 24 часов</p>
            </div>
            {sent ? (
              <div className="sw-success">
                <div className="sw-success-ico">
                  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#059669" strokeWidth="2.5"><polyline points="20 6 9 17 4 12"/></svg>
                </div>
                <h4>Обращение отправлено!</h4>
                <p>Мы получили ваш запрос и ответим в ближайшее время на указанный email или по телефону.</p>
              </div>
            ) : (
              <form className="sw-body" onSubmit={submit}>
                <div className="sw-field">
                  <label className="sw-label">Ваше имя *</label>
                  <input className="sw-input" value={form.name} onChange={e => set('name', e.target.value)} placeholder="Имя" />
                </div>
                <div className="sw-field">
                  <label className="sw-label">Email</label>
                  <input className="sw-input" type="email" value={form.email} onChange={e => set('email', e.target.value)} placeholder="example@mail.com" />
                </div>
                <div className="sw-field">
                  <label className="sw-label">Телефон</label>
                  <input className="sw-input" type="tel" value={form.phone} onChange={e => set('phone', e.target.value)} placeholder="+7 (___) ___-__-__" />
                </div>
                <div className="sw-field">
                  <label className="sw-label">Тема *</label>
                  <input className="sw-input" value={form.subject} onChange={e => set('subject', e.target.value)} placeholder="Кратко опишите проблему" />
                </div>
                <div className="sw-field">
                  <label className="sw-label">Сообщение *</label>
                  <textarea className="sw-textarea" value={form.message} onChange={e => set('message', e.target.value)} placeholder="Подробно опишите ваш вопрос..." />
                </div>
                {error && <div className="sw-err">{error}</div>}
                <button className="sw-submit" disabled={loading}>
                  {loading ? 'Отправляем...' : 'Отправить обращение'}
                </button>
              </form>
            )}
          </div>
        )}
        <button className={`sw-btn ${open ? 'open' : ''}`} onClick={handleOpen} title="Техническая поддержка">
          {open ? (
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
          ) : (
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
          )}
        </button>
      </div>
    </>
  )
}
