import { useState, useCallback } from 'react'
import { useStore } from '../store'
import { apiNcaChallenge, apiNcaAuth, apiMe } from '../api'
import { ncaLayer, toBase64, NCALayerError, type NCAKeyInfo } from '../utils/ncalayer'
import { useToast } from './Toast'

type Step = 'idle' | 'connecting' | 'challenge' | 'browsing' | 'selecting' | 'signing' | 'verifying' | 'success' | 'error'

const css = `
.nca-overlay { position:fixed;inset:0;background:rgba(15,15,35,.65);backdrop-filter:blur(4px);z-index:1100;display:flex;align-items:center;justify-content:center;padding:16px; }
.nca-box { background:#fff;border-radius:20px;padding:32px 28px 26px;width:100%;max-width:420px;box-shadow:0 24px 64px rgba(0,0,0,.2);position:relative; }
.nca-close { position:absolute;top:14px;right:14px;width:30px;height:30px;border-radius:50%;border:none;background:none;display:flex;align-items:center;justify-content:center;cursor:pointer;color:#94A3B8;transition:all .2s; }
.nca-close:hover { background:#F1F5F9;color:#475569; }
.nca-head { display:flex;align-items:center;gap:10px;margin-bottom:20px; }
.nca-icon { width:40px;height:40px;background:linear-gradient(135deg,#5B4FE8,#3B82F6);border-radius:12px;display:flex;align-items:center;justify-content:center; }
.nca-title { font-size:19px;font-weight:800;color:#1E1B4B; }
.nca-sub { font-size:13px;color:#64748B;margin-top:2px; }
.steps { display:flex;align-items:center;gap:4px;margin-bottom:22px; }
.step-dot { width:8px;height:8px;border-radius:50%;background:#E2E8F0;transition:all .3s; }
.step-dot.active { background:#5B4FE8;transform:scale(1.2); }
.step-dot.done { background:#10B981; }
.step-label { font-size:12px;color:#64748B;margin-bottom:18px;min-height:32px; }
.nca-spinner { width:36px;height:36px;border:3px solid #E2E8F0;border-top-color:#5B4FE8;border-radius:50%;animation:spin .8s linear infinite;margin:20px auto; }
@keyframes spin { to { transform:rotate(360deg); } }
.nca-alert { background:#FFF7ED;border:1px solid #FED7AA;border-radius:10px;padding:12px 14px;font-size:13px;color:#92400E;display:flex;gap:8px;align-items:flex-start; }
.nca-alert svg { flex-shrink:0;margin-top:1px; }
.cert-list { display:flex;flex-direction:column;gap:8px;max-height:220px;overflow-y:auto;margin-bottom:16px; }
.cert-item { padding:11px 14px;border:1.5px solid #E2E8F0;border-radius:10px;cursor:pointer;transition:all .2s; }
.cert-item:hover { border-color:#5B4FE8;background:#F5F3FF; }
.cert-item.selected { border-color:#5B4FE8;background:#EEF2FF; }
.cert-cn { font-size:14px;font-weight:700;color:#1E1B4B; }
.cert-dn { font-size:11px;color:#94A3B8;margin-top:2px;word-break:break-all; }
.cert-exp { font-size:11px;color:#64748B;margin-top:3px; }
.nca-btn { width:100%;height:46px;border-radius:12px;background:linear-gradient(135deg,#5B4FE8,#3B82F6);color:#fff;font-size:15px;font-weight:700;border:none;cursor:pointer;transition:opacity .2s; }
.nca-btn:hover:not(:disabled) { opacity:.9; }
.nca-btn:disabled { opacity:.5;cursor:not-allowed; }
.nca-btn-ghost { width:100%;height:40px;border-radius:10px;border:1.5px solid #E2E8F0;background:#fff;color:#475569;font-size:14px;font-weight:600;cursor:pointer;margin-top:8px;transition:all .2s; }
.nca-btn-ghost:hover { border-color:#5B4FE8;color:#5B4FE8; }
.success-box { text-align:center;padding:10px 0 4px; }
.success-icon { width:64px;height:64px;background:#D1FAE5;border-radius:50%;display:flex;align-items:center;justify-content:center;margin:0 auto 14px; }
.success-name { font-size:18px;font-weight:800;color:#1E1B4B;margin-bottom:4px; }
.success-iin { font-size:14px;color:#64748B;margin-bottom:6px; }
.success-badge { display:inline-flex;align-items:center;gap:5px;background:#D1FAE5;color:#065F46;padding:4px 10px;border-radius:20px;font-size:12px;font-weight:700;margin-bottom:18px; }
.err-box { background:#FEF2F2;border:1px solid #FCA5A5;border-radius:10px;padding:12px 14px;font-size:13px;color:#DC2626;margin-bottom:16px; }
.nca-install { font-size:12px;color:#94A3B8;text-align:center;margin-top:12px; }
.nca-install a { color:#5B4FE8; }
`

const STEPS = ['connecting', 'challenge', 'browsing', 'selecting', 'signing', 'verifying']

function stepIndex(step: Step): number {
  return STEPS.indexOf(step)
}

function StepDots({ current }: { current: Step }) {
  const ci = stepIndex(current)
  return (
    <div className="steps">
      {STEPS.map((s, i) => (
        <div key={s} className={`step-dot ${i < ci ? 'done' : i === ci ? 'active' : ''}`} />
      ))}
    </div>
  )
}

export default function NCAVerifyModal() {
  const { ncaOpen, closeNCA, token, setToken, setUser, closeAuth } = useStore()
  const [step, setStep] = useState<Step>('idle')
  const [err, setErr] = useState('')
  const [keys, setKeys] = useState<NCAKeyInfo[]>([])
  const [selectedKey, setSelectedKey] = useState<NCAKeyInfo | null>(null)
  const [store, setStore] = useState('PKCS12')
  const [successInfo, setSuccessInfo] = useState<{ name: string; iin: string } | null>(null)
  const { show: toast } = useToast()

  const reset = useCallback(() => {
    setStep('idle')
    setErr('')
    setKeys([])
    setSelectedKey(null)
    setSuccessInfo(null)
  }, [])

  const handleClose = useCallback(() => {
    closeNCA()
    reset()
  }, [closeNCA, reset])

  const stepLabel: Record<Step, string> = {
    idle: 'Подпишите вход через ваш ЭЦП (NCALayer). Сертификат используется для подтверждения ИИН/БИН.',
    connecting: 'Подключение к NCALayer...',
    challenge: 'Получение задания для подписи...',
    browsing: 'Укажите файл ЭЦП и введите пароль в диалоге NCALayer (может занять до нескольких минут).',
    selecting: 'Выберите сертификат для подписи:',
    signing: 'Подписываем данные...',
    verifying: 'Проверяем подпись на сервере...',
    success: '',
    error: '',
  }

  async function start() {
    setErr('')
    let challengeId = ''
    let challenge = ''

    try {
      setStep('connecting')
      await ncaLayer.connect()

      setStep('challenge')
      const ch = await apiNcaChallenge()
      challengeId = ch.challenge_id
      challenge = ch.challenge

      setStep('browsing')
      let storageName = 'PKCS12'
      try {
        const tokens = await ncaLayer.getActiveTokens()
        storageName = tokens[0] || 'PKCS12'
      } catch {}

      const browsedStore = await ncaLayer.browseKeyStore(storageName)
      const actualStore = browsedStore || storageName
      setStore(actualStore)

      setStep('selecting')
      let keyList: NCAKeyInfo[] = []
      try {
        keyList = await ncaLayer.getKeyList(actualStore)
      } catch {
        keyList = [{ alias: actualStore, subjectDn: actualStore, subjectCn: 'Выбранный сертификат' }]
      }
      setKeys(keyList)

      if (keyList.length === 1) {
        await signWithKey(keyList[0], actualStore, challengeId, challenge)
      }
      // else wait for user to pick
    } catch (e) {
      const msg = e instanceof NCALayerError ? e.message : (e instanceof Error ? e.message : 'Ошибка NCALayer')
      setErr(msg)
      setStep('error')
    }

    // stash for use in signWithKey after selection
    ;(window as any).__nca_pending = { challengeId, challenge }
  }

  async function signWithKey(key: NCAKeyInfo, storeName: string, challengeId: string, challenge: string) {
    setSelectedKey(key)
    setStep('signing')
    const dataB64 = toBase64(challenge)
    const cms = await ncaLayer.signPlainData(storeName, key.alias, dataB64)

    setStep('verifying')
    const authResult = await apiNcaAuth({ challenge_id: challengeId, cms_signature: cms })

    // Update store with NCA token
    setToken(authResult.access_token)
    const me = await apiMe(authResult.access_token)
    setUser(me)
    closeAuth()

    setSuccessInfo({ name: authResult.full_name, iin: authResult.iin })
    setStep('success')
    toast('ИИН подтверждён! Вы вошли через ЭЦП.', 'success')
  }

  async function handleSelectKey(key: NCAKeyInfo) {
    const pending = (window as any).__nca_pending
    if (!pending) { setErr('Сессия истекла. Начните заново.'); setStep('error'); return }
    try {
      await signWithKey(key, store, pending.challengeId, pending.challenge)
    } catch (e) {
      const msg = e instanceof NCALayerError ? e.message : (e instanceof Error ? e.message : 'Ошибка подписи')
      setErr(msg)
      setStep('error')
    }
  }

  if (!ncaOpen) return null

  return (
    <>
      <style>{css}</style>
      <div className="nca-overlay" onClick={handleClose}>
        <div className="nca-box" onClick={e => e.stopPropagation()}>
          <button className="nca-close" onClick={handleClose}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path d="M18 6 6 18M6 6l12 12"/></svg>
          </button>

          <div className="nca-head">
            <div className="nca-icon">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="2.5"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
            </div>
            <div>
              <div className="nca-title">Вход через ЭЦП</div>
              <div className="nca-sub">Цифровая подпись Казахстан</div>
            </div>
          </div>

          {step !== 'idle' && step !== 'success' && step !== 'error' && <StepDots current={step} />}

          {step === 'success' && successInfo ? (
            <div className="success-box">
              <div className="success-icon">
                <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#059669" strokeWidth="2.5"><path d="M20 6 9 17l-5-5"/></svg>
              </div>
              <div className="success-name">{successInfo.name}</div>
              <div className="success-iin">ИИН: {successInfo.iin}</div>
              <div className="success-badge">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
                Личность подтверждена
              </div>
              <button className="nca-btn" onClick={handleClose}>Отлично!</button>
            </div>
          ) : step === 'error' ? (
            <>
              <div className="err-box">{err}</div>
              <button className="nca-btn" onClick={start}>Попробовать снова</button>
              <button className="nca-btn-ghost" onClick={handleClose}>Отмена</button>
              <div className="nca-install">
                Нет NCALayer? <a href="https://ncalayer.pki.gov.kz" target="_blank" rel="noreferrer">Скачать</a>
              </div>
            </>
          ) : step === 'selecting' && keys.length > 1 ? (
            <>
              <div className="step-label">{stepLabel.selecting}</div>
              <div className="cert-list">
                {keys.map(k => (
                  <div key={k.alias} className={`cert-item ${selectedKey?.alias === k.alias ? 'selected' : ''}`} onClick={() => handleSelectKey(k)}>
                    <div className="cert-cn">{k.subjectCn || k.alias}</div>
                    <div className="cert-dn">{k.subjectDn}</div>
                    {k.notAfter && <div className="cert-exp">Действует до: {k.notAfter}</div>}
                  </div>
                ))}
              </div>
            </>
          ) : step === 'idle' ? (
            <>
              <div className="step-label">{stepLabel.idle}</div>
              <div className="nca-alert">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10"/><path d="M12 8v4M12 16h.01"/></svg>
                NCALayer должен быть установлен и запущен на вашем компьютере.
              </div>
              <br />
              <button className="nca-btn" onClick={start}>
                Подключить ЭЦП
              </button>
              <div className="nca-install">
                Нет NCALayer? <a href="https://ncalayer.pki.gov.kz" target="_blank" rel="noreferrer">Скачать на pki.gov.kz</a>
              </div>
            </>
          ) : (
            <>
              <div className="step-label">{stepLabel[step]}</div>
              {step === 'browsing' && (
                <div className="nca-alert">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10"/><path d="M12 8v4M12 16h.01"/></svg>
                  Откройте окно NCALayer, выберите файл ЭЦП (.p12) и введите пароль.
                </div>
              )}
              <div className="nca-spinner" />
            </>
          )}
        </div>
      </div>
    </>
  )
}
