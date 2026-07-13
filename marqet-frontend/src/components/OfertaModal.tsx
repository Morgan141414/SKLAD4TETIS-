import { useState, useEffect } from 'react'
import { useStore } from '../store'
import { apiGetOferta, apiSignOferta, apiMe } from '../api'
import { ncaLayer, toBase64, NCALayerError } from '../utils/ncalayer'
import { useToast } from './Toast'

type Step = 'loading' | 'show' | 'connecting' | 'browsing' | 'signing' | 'verifying' | 'success' | 'error'

const css = `
.of-overlay { position:fixed;inset:0;background:rgba(15,15,35,.65);backdrop-filter:blur(4px);z-index:1100;display:flex;align-items:center;justify-content:center;padding:16px; }
.of-box { background:#fff;border-radius:20px;padding:28px 26px 22px;width:100%;max-width:540px;max-height:90vh;display:flex;flex-direction:column;box-shadow:0 24px 64px rgba(0,0,0,.2);position:relative; }
.of-close { position:absolute;top:14px;right:14px;width:30px;height:30px;border-radius:50%;border:none;background:none;display:flex;align-items:center;justify-content:center;cursor:pointer;color:#94A3B8;transition:all .2s; }
.of-close:hover { background:#F1F5F9;color:#475569; }
.of-title { font-size:19px;font-weight:800;color:#1E1B4B;margin-bottom:4px; }
.of-sub { font-size:13px;color:#64748B;margin-bottom:14px; }
.of-text { flex:1;overflow-y:auto;border:1px solid #E2E8F0;border-radius:10px;padding:14px;font-size:12.5px;line-height:1.7;color:#374151;white-space:pre-wrap;background:#F8FAFC;min-height:220px;max-height:320px;margin-bottom:14px; }
.of-version { font-size:11px;color:#94A3B8;margin-bottom:12px; }
.of-status { background:#FFF7ED;border:1px solid #FED7AA;border-radius:10px;padding:10px 14px;font-size:13px;color:#92400E;margin-bottom:12px; }
.of-spinner { width:30px;height:30px;border:3px solid #E2E8F0;border-top-color:#5B4FE8;border-radius:50%;animation:spinof .8s linear infinite;margin:16px auto; }
@keyframes spinof { to { transform:rotate(360deg); } }
.of-btn { width:100%;height:46px;border-radius:12px;background:linear-gradient(135deg,#5B4FE8,#3B82F6);color:#fff;font-size:15px;font-weight:700;border:none;cursor:pointer;transition:opacity .2s; }
.of-btn:hover:not(:disabled) { opacity:.9; }
.of-btn:disabled { opacity:.5; }
.of-btn-ghost { width:100%;height:40px;border-radius:10px;border:1.5px solid #E2E8F0;background:#fff;color:#475569;font-size:14px;font-weight:600;cursor:pointer;margin-top:8px;transition:all .2s; }
.of-btn-ghost:hover { border-color:#5B4FE8;color:#5B4FE8; }
.err-box { background:#FEF2F2;border:1px solid #FCA5A5;border-radius:10px;padding:10px 14px;font-size:13px;color:#DC2626;margin-bottom:12px; }
.of-success { text-align:center;padding:10px 0; }
.of-sicon { width:56px;height:56px;background:#D1FAE5;border-radius:50%;display:flex;align-items:center;justify-content:center;margin:0 auto 12px; }
.of-sname { font-size:17px;font-weight:800;color:#1E1B4B;margin-bottom:4px; }
.of-sbadge { display:inline-flex;align-items:center;gap:5px;background:#D1FAE5;color:#065F46;padding:4px 10px;border-radius:20px;font-size:12px;font-weight:700;margin:8px 0 18px; }
.of-step-hint { font-size:13px;color:#64748B;text-align:center;margin-bottom:8px;min-height:36px; }
.of-alert { background:#FFF7ED;border:1px solid #FED7AA;border-radius:10px;padding:10px 14px;font-size:12.5px;color:#92400E;display:flex;gap:7px;align-items:flex-start;margin-bottom:10px; }
`

const stepHints: Partial<Record<Step, string>> = {
  connecting: 'Подключение к NCALayer...',
  browsing: 'Выберите файл ЭЦП в диалоге NCALayer и введите пароль',
  signing: 'Подписываем оферту...',
  verifying: 'Отправляем подпись на сервер...',
}

export default function OfertaModal({ onSigned }: { onSigned?: () => void }) {
  const { ofertaOpen, closeOferta, token } = useStore()
  const [step, setStep] = useState<Step>('loading')
  const [oferta, setOferta] = useState<{ version: string; text: string } | null>(null)
  const [err, setErr] = useState('')
  const [successInfo, setSuccessInfo] = useState<{ name: string; iin: string } | null>(null)
  const { show: toast } = useToast()

  useEffect(() => {
    if (!ofertaOpen) return
    setStep('loading')
    setErr('')
    setSuccessInfo(null)
    apiGetOferta()
      .then(data => { setOferta(data); setStep('show') })
      .catch(() => { setErr('Не удалось загрузить оферту'); setStep('error') })
  }, [ofertaOpen])

  async function signOferta() {
    if (!oferta) return
    setErr('')
    try {
      setStep('connecting')
      if (!ncaLayer.isConnected()) await ncaLayer.connect()

      setStep('browsing')
      let storageName = 'PKCS12'
      try {
        const tokens = await ncaLayer.getActiveTokens()
        storageName = tokens[0] || 'PKCS12'
      } catch {}
      const browsedStore = await ncaLayer.browseKeyStore(storageName)
      const actualStore = browsedStore || storageName

      let alias = actualStore
      try {
        const keyList = await ncaLayer.getKeyList(actualStore)
        if (keyList.length > 0) alias = keyList[0].alias
      } catch {}

      setStep('signing')
      const dataB64 = toBase64(oferta.text)
      const cms = await ncaLayer.signPlainData(actualStore, alias, dataB64)

      setStep('verifying')
      const result = await apiSignOferta({ cms_signature: cms, oferta_version: oferta.version })

      setSuccessInfo({ name: result.full_name, iin: result.iin })
      setStep('success')
      toast('Оферта подписана! Теперь вы можете публиковать объявления.', 'success')
      onSigned?.()
    } catch (e) {
      const msg = e instanceof NCALayerError ? e.message : (e instanceof Error ? e.message : 'Ошибка подписи')
      setErr(msg)
      setStep('error')
    }
  }

  if (!ofertaOpen) return null

  return (
    <>
      <style>{css}</style>
      <div className="of-overlay" onClick={closeOferta}>
        <div className="of-box" onClick={e => e.stopPropagation()}>
          <button className="of-close" onClick={closeOferta}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path d="M18 6 6 18M6 6l12 12"/></svg>
          </button>

          {step === 'loading' && <div className="of-spinner" />}

          {step === 'show' && oferta && (
            <>
              <div className="of-title">Публичная оферта</div>
              <div className="of-sub">Ознакомьтесь с условиями перед подачей объявления</div>
              <div className="of-text">{oferta.text}</div>
              <div className="of-version">Версия: {oferta.version}</div>
              <div className="of-status">
                Для публикации объявлений необходимо подписать оферту через ЭЦП (NCALayer). NCALayer должен быть установлен и запущен.
              </div>
              <button className="of-btn" onClick={signOferta}>
                Подписать через ЭЦП
              </button>
              <button className="of-btn-ghost" onClick={closeOferta}>Закрыть</button>
            </>
          )}

          {['connecting', 'browsing', 'signing', 'verifying'].includes(step) && (
            <>
              <div className="of-title">Подписание оферты</div>
              <br />
              {step === 'browsing' && (
                <div className="of-alert">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10"/><path d="M12 8v4M12 16h.01"/></svg>
                  Откройте диалог NCALayer, выберите файл .p12 и введите пароль к ЭЦП.
                </div>
              )}
              <div className="of-step-hint">{stepHints[step]}</div>
              <div className="of-spinner" />
            </>
          )}

          {step === 'success' && successInfo && (
            <div className="of-success">
              <div className="of-sicon">
                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#059669" strokeWidth="2.5"><path d="M20 6 9 17l-5-5"/></svg>
              </div>
              <div className="of-sname">{successInfo.name}</div>
              <div style={{ fontSize: 13, color: '#64748B' }}>ИИН: {successInfo.iin}</div>
              <div className="of-sbadge">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
                Оферта подписана
              </div>
              <button className="of-btn" onClick={closeOferta}>Продолжить</button>
            </div>
          )}

          {step === 'error' && (
            <>
              <div className="of-title">Ошибка</div>
              <br />
              <div className="err-box">{err}</div>
              <button className="of-btn" onClick={signOferta}>Попробовать снова</button>
              <button className="of-btn-ghost" onClick={closeOferta}>Отмена</button>
            </>
          )}
        </div>
      </div>
    </>
  )
}
