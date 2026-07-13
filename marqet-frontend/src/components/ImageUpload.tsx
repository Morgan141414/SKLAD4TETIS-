import { useRef, useState } from 'react'

const css = `
.img-upload-wrap { border:2px dashed #C7D2FE; border-radius:12px; padding:20px; text-align:center; background:#F8FAFC; transition:all .2s; cursor:pointer; }
.img-upload-wrap:hover, .img-upload-wrap.drag { border-color:#5B4FE8; background:#EEF2FF; }
.img-upload-wrap input { display:none; }
.img-preview { width:100%; aspect-ratio:4/3; border-radius:10px; object-fit:cover; margin-bottom:8px; }
.img-upload-txt { font-size:14px; color:#64748B; }
.img-upload-ico { font-size:32px; margin-bottom:8px; display:block; }
.img-upload-progress { background:#E2E8F0; border-radius:4px; height:4px; margin-top:8px; overflow:hidden; }
.img-upload-bar { background:var(--brand-grad); height:100%; transition:width .3s; }
.img-upload-err { color:#EF4444; font-size:12px; margin-top:6px; }
.img-upload-ok { color:#059669; font-size:12px; margin-top:6px; }
.btn-remove-img { background:#FEF2F2; color:#EF4444; border:none; border-radius:8px; padding:6px 14px; font-size:12px; font-weight:700; cursor:pointer; margin-top:6px; }
`

export default function ImageUpload({ value, onChange }: { value: string; onChange: (url: string) => void }) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [uploading, setUploading] = useState(false)
  const [progress, setProgress] = useState(0)
  const [err, setErr] = useState('')
  const [drag, setDrag] = useState(false)

  async function handleFile(file: File) {
    setErr('')
    if (!file.type.startsWith('image/')) { setErr('Только изображения'); return }
    if (file.size > 10 * 1024 * 1024) { setErr('Максимум 10 МБ'); return }
    setUploading(true)
    setProgress(30)
    try {
      const tok = (() => { try { const r=localStorage.getItem('marqet-auth'); if(!r) return null; return JSON.parse(r)?.state?.token??null }catch{return null} })()
      const fd = new FormData()
      fd.append('file', file)
      setProgress(60)
      const res = await fetch('/api/v1/marketplace/upload-image', {
        method: 'POST',
        headers: tok ? { Authorization: `Bearer ${tok}` } : {},
        body: fd,
      })
      setProgress(90)
      if (!res.ok) { const e = await res.json().catch(()=>({})); throw new Error(e?.detail?.message||'Ошибка загрузки') }
      const data = await res.json()
      onChange(data.url)
      setProgress(100)
    } catch (e: any) {
      setErr(e?.message || 'Ошибка загрузки')
    } finally {
      setUploading(false)
      setTimeout(() => setProgress(0), 1000)
    }
  }

  function onDrop(e: React.DragEvent) {
    e.preventDefault(); setDrag(false)
    const file = e.dataTransfer.files[0]
    if (file) handleFile(file)
  }

  return (
    <>
      <style>{css}</style>
      <div
        className={`img-upload-wrap ${drag ? 'drag' : ''}`}
        onClick={() => !value && inputRef.current?.click()}
        onDragOver={e => { e.preventDefault(); setDrag(true) }}
        onDragLeave={() => setDrag(false)}
        onDrop={onDrop}
      >
        <input ref={inputRef} type="file" accept="image/*" onChange={e => { const f=e.target.files?.[0]; if(f) handleFile(f) }} />
        {value ? (
          <>
            <img className="img-preview" src={value} alt="preview" />
            <div style={{display:'flex',gap:8,justifyContent:'center'}}>
              <button type="button" className="btn-remove-img" onClick={e => { e.stopPropagation(); onChange(''); }}>✕ Удалить</button>
              <button type="button" style={{background:'#EEF2FF',color:'#5B4FE8',border:'none',borderRadius:8,padding:'6px 14px',fontSize:12,fontWeight:700,cursor:'pointer'}} onClick={e => { e.stopPropagation(); inputRef.current?.click() }}>Заменить</button>
            </div>
            <div className="img-upload-ok">✓ Фото загружено</div>
          </>
        ) : (
          <>
            <span className="img-upload-ico">📷</span>
            <div className="img-upload-txt">{uploading ? 'Загружаю...' : 'Перетащите фото или нажмите для выбора'}</div>
            <div className="img-upload-txt" style={{fontSize:11,marginTop:4,color:'#CBD5E1'}}>JPG, PNG, WebP — до 10 МБ</div>
          </>
        )}
        {progress > 0 && progress < 100 && (
          <div className="img-upload-progress"><div className="img-upload-bar" style={{width:`${progress}%`}} /></div>
        )}
        {err && <div className="img-upload-err">{err}</div>}
      </div>
    </>
  )
}
