import { useState } from 'react'
import { useStore } from '../store'
import { apiRegister, apiLogin, apiMe } from '../api'

const css = `
.modal-overlay { position:fixed; inset:0; background:rgba(15,15,35,.6); backdrop-filter:blur(4px); z-index:1000; display:flex; align-items:center; justify-content:center; padding:16px; }
.modal-box { background:#fff; border-radius:20px; padding:36px 32px 28px; width:100%; max-width:400px; box-shadow:0 24px 64px rgba(0,0,0,.18); position:relative; }
.modal-close { position:absolute; top:16px; right:16px; background:none; border:none; width:32px; height:32px; border-radius:50%; display:flex; align-items:center; justify-content:center; cursor:pointer; color:#94A3B8; transition:all .2s; }
.modal-close:hover { background:#F1F5F9; color:#475569; }
.modal-logo { display:flex; align-items:center; gap:8px; font-size:17px; font-weight:800; color:#1E1B4B; margin-bottom:22px; }
.modal-logo span { background:linear-gradient(135deg,#5B4FE8,#3B82F6); -webkit-background-clip:text; -webkit-text-fill-color:transparent; }
.modal-title { font-size:22px; font-weight:800; color:#1E1B4B; margin-bottom:4px; }
.modal-sub { font-size:14px; color:#64748B; margin-bottom:24px; }
.inp-group { margin-bottom:14px; }
.inp-label { font-size:12px; font-weight:600; color:#475569; margin-bottom:5px; }
.inp-field { width:100%; height:44px; padding:0 14px; border:1.5px solid #E2E8F0; border-radius:10px; font-size:14px; outline:none; transition:all .2s; background:#FAFAFA; box-sizing:border-box; }
.inp-field:focus { border-color:#5B4FE8; background:#fff; box-shadow:0 0 0 3px rgba(91,79,232,.1); }
.err-msg { background:#FEF2F2; border:1px solid #FCA5A5; border-radius:8px; padding:10px 14px; font-size:13px; color:#DC2626; margin-bottom:14px; }
.btn-submit { width:100%; height:46px; border:none; border-radius:12px; background:var(--brand-grad); color:#fff; font-size:15px; font-weight:700; transition:opacity .2s; margin-top:4px; }
.btn-submit:hover:not(:disabled) { opacity:.9; }
.btn-submit:disabled { opacity:.6; }
.modal-toggle { text-align:center; margin-top:18px; font-size:14px; color:#64748B; }
.modal-toggle button { background:none; border:none; color:#5B4FE8; font-weight:700; font-size:14px; cursor:pointer; }
.modal-toggle button:hover { text-decoration:underline; }
.nca-divider { display:flex;align-items:center;gap:10px;margin:18px 0 4px; }
.nca-divider span { font-size:11px;color:#CBD5E1;white-space:nowrap; }
.nca-divider hr { flex:1;border:none;border-top:1px solid #E2E8F0; }
.btn-nca { width:100%;height:46px;border:2px solid #E2E8F0;border-radius:12px;background:#fff;display:flex;align-items:center;justify-content:center;gap:8px;font-size:14px;font-weight:700;color:#1E1B4B;cursor:pointer;transition:all .2s;margin-top:4px; }
.btn-nca:hover { border-color:#5B4FE8;color:#5B4FE8;background:#F5F3FF; }

.divider { text-align:center; font-size:12px; color:#94A3B8; margin:16px 0 4px; }
`

const SmallLogo = () => (
  <svg width="24" height="24" viewBox="0 0 120 120" fill="none">
    <defs><linearGradient id="slg" x1="0" y1="0" x2="1" y2="1"><stop offset="0%" stopColor="#5B4FE8"/><stop offset="100%" stopColor="#3B82F6"/></linearGradient></defs>
    <path d="M20 35 L30 35 L44 80 L96 80 L106 45 L34 45" stroke="#1E1B4B" strokeWidth="8" strokeLinecap="round" strokeLinejoin="round" fill="none"/>
    <circle cx="50" cy="94" r="8" fill="#1E1B4B"/>
    <circle cx="88" cy="94" r="8" fill="#1E1B4B"/>
    <path d="M42 70 L42 45 L62 62 L82 45 L82 70" stroke="url(#slg)" strokeWidth="9" strokeLinecap="round" strokeLinejoin="round" fill="none"/>
  </svg>
)

export default function AuthModal() {
  const { authMode, closeAuth, setToken, setUser, openAuth, openNCA } = useStore()
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [phone, setPhone] = useState('')
  const [pass, setPass] = useState('')
  const [err, setErr] = useState('')
  const [loading, setLoading] = useState(false)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setErr('')
    setLoading(true)
    try {
      let token: string
      if (authMode === 'register') {
        const r = await apiRegister({ name, email, phone: phone || undefined, password: pass })
        token = r.access_token
      } else {
        const r = await apiLogin({ email, password: pass })
        token = r.access_token
      }
      setToken(token)
      const me = await apiMe(token)
      setUser(me)
      closeAuth()
    } catch (e: any) {
      setErr(e?.message || 'Ошибка. Попробуйте ещё раз.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <>
      <style>{css}</style>
      <div className="modal-overlay" onClick={closeAuth}>
        <div className="modal-box" onClick={e => e.stopPropagation()}>
          <button className="modal-close" onClick={closeAuth}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path d="M18 6 6 18M6 6l12 12"/></svg>
          </button>

          <div className="modal-logo">
            <SmallLogo />
            <span>marqet</span>.kz
          </div>

          <div className="modal-title">{authMode === 'login' ? 'Добро пожаловать!' : 'Создать аккаунт'}</div>
          <div className="modal-sub">{authMode === 'login' ? 'Войдите, чтобы продолжить' : 'Регистрация займёт минуту'}</div>

          {err && <div className="err-msg">{err}</div>}

          <form onSubmit={submit}>
            {authMode === 'register' && (
              <div className="inp-group">
                <div className="inp-label">Имя</div>
                <input className="inp-field" placeholder="Ваше имя" value={name} onChange={e => setName(e.target.value)} required minLength={2} />
              </div>
            )}
            <div className="inp-group">
              <div className="inp-label">Email</div>
              <input className="inp-field" type="email" placeholder="you@example.com" value={email} onChange={e => setEmail(e.target.value)} required />
            </div>
            {authMode === 'register' && (
              <div className="inp-group">
                <div className="inp-label">Телефон (необязательно)</div>
                <input className="inp-field" placeholder="+7 777 000 0000" value={phone} onChange={e => setPhone(e.target.value)} />
              </div>
            )}
            <div className="inp-group">
              <div className="inp-label">Пароль</div>
              <input className="inp-field" type="password" placeholder={authMode === 'register' ? 'Минимум 8 символов' : 'Ваш пароль'} value={pass} onChange={e => setPass(e.target.value)} required minLength={8} />
            </div>
            <button className="btn-submit" type="submit" disabled={loading}>
              {loading ? 'Подождите...' : authMode === 'login' ? 'Войти' : 'Зарегистрироваться'}
            </button>
          </form>

          <div className="modal-toggle">
            {authMode === 'login' ? (
              <>Нет аккаунта? <button onClick={() => openAuth('register')}>Создать</button></>
            ) : (
              <>Уже есть аккаунт? <button onClick={() => openAuth('login')}>Войти</button></>
            )}
          </div>
          <div className="nca-divider"><hr /><span>или</span><hr /></div>
          <button className="btn-nca" type="button" onClick={() => { closeAuth(); openNCA() }}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
            Войти через ЭЦП (NCALayer)
          </button>
        </div>
      </div>
    </>
  )
}
