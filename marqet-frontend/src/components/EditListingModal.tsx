import { useState } from 'react'
import { apiUpdateListing } from '../api'
import { useToast } from './Toast'
import ImageUpload from './ImageUpload'

const CATEGORIES = [
  'Электроника','Автомобили','Авто-запчасти','Мебель','Бытовая техника',
  'Одежда','Обувь','Детские товары','Спорт','Фото и видео',
  'Аксессуары','Электротранспорт','Другое',
]

interface Listing {
  id: number; product_name: string; unit_price: number | null; unit: string;
  category: string | null; description: string | null; image_url: string | null;
  is_active: boolean; created_at: string; supplier_phone: string | null; city: string | null;
}

const css = `
.edit-overlay { position:fixed; inset:0; background:rgba(15,15,35,.6); z-index:600; display:flex; align-items:center; justify-content:center; padding:16px; overflow-y:auto; }
.edit-box { background:#fff; border-radius:20px; padding:28px 24px; width:100%; max-width:520px; position:relative; max-height:90vh; overflow-y:auto; }
.edit-box h2 { font-size:20px; font-weight:800; color:#1E1B4B; margin-bottom:20px; }
.edit-close { position:absolute; top:16px; right:16px; background:none; border:none; font-size:20px; cursor:pointer; color:#94A3B8; width:32px; height:32px; display:flex; align-items:center; justify-content:center; border-radius:50%; }
.edit-close:hover { background:#F1F5F9; color:#475569; }
.ef { margin-bottom:14px; }
.ef label { display:block; font-size:12px; font-weight:700; color:#475569; margin-bottom:5px; }
.ef input, .ef textarea, .ef select { width:100%; padding:10px 13px; border:1.5px solid #E2E8F0; border-radius:10px; font-size:14px; font-family:inherit; outline:none; transition:all .2s; background:#FAFAFA; box-sizing:border-box; }
.ef input:focus, .ef textarea:focus, .ef select:focus { border-color:#5B4FE8; background:#fff; box-shadow:0 0 0 3px rgba(91,79,232,.1); }
.ef textarea { min-height:80px; resize:vertical; }
.ef-row { display:grid; grid-template-columns:1fr 1fr; gap:10px; }
.btn-save { width:100%; height:46px; border-radius:12px; background:var(--brand-grad); color:#fff; font-size:15px; font-weight:700; border:none; cursor:pointer; transition:opacity .2s; }
.btn-save:hover:not(:disabled) { opacity:.9; }
.btn-save:disabled { opacity:.6; }
`

export default function EditListingModal({ item, onClose, onSaved }: {
  item: Listing; onClose: () => void; onSaved: (updated: any) => void
}) {
  const { show } = useToast()
  const [title, setTitle] = useState(item.product_name)
  const [desc, setDesc] = useState(item.description || '')
  const [price, setPrice] = useState(item.unit_price != null ? String(item.unit_price) : '')
  const [unit, setUnit] = useState(item.unit || 'шт')
  const [cat, setCat] = useState(item.category || '')
  const [phone, setPhone] = useState(item.supplier_phone || '')
  const [city, setCity] = useState(item.city || '')
  const [imageUrl, setImageUrl] = useState(item.image_url || '')
  const [loading, setLoading] = useState(false)

  async function save(e: React.FormEvent) {
    e.preventDefault()
    setLoading(true)
    try {
      await apiUpdateListing(item.id, {
        title: title.trim() || undefined,
        description: desc.trim() || undefined,
        price: price ? parseFloat(price) : undefined,
        unit: unit || undefined,
        category: cat || undefined,
        phone: phone.trim() || undefined,
        image_url: imageUrl || undefined,
      })
      show('Объявление обновлено')
      onSaved({ ...item, product_name: title, description: desc, unit_price: price ? parseFloat(price) : null, unit, category: cat, supplier_phone: phone, city, image_url: imageUrl })
      onClose()
    } catch (e: any) {
      show(e?.message || 'Ошибка сохранения', 'error')
    } finally {
      setLoading(false)
    }
  }

  return (
    <>
      <style>{css}</style>
      <div className="edit-overlay" onClick={onClose}>
        <div className="edit-box" onClick={e => e.stopPropagation()}>
          <button className="edit-close" onClick={onClose}>✕</button>
          <h2>Редактировать объявление</h2>
          <form onSubmit={save}>
            <div className="ef">
              <label>Фото</label>
              <ImageUpload value={imageUrl} onChange={setImageUrl} />
            </div>
            <div className="ef">
              <label>Название</label>
              <input value={title} onChange={e => setTitle(e.target.value)} maxLength={200} required />
            </div>
            <div className="ef">
              <label>Описание</label>
              <textarea value={desc} onChange={e => setDesc(e.target.value)} maxLength={2000} />
            </div>
            <div className="ef">
              <label>Категория</label>
              <select value={cat} onChange={e => setCat(e.target.value)}>
                <option value="">Не указана</option>
                {CATEGORIES.map(c => <option key={c} value={c}>{c}</option>)}
              </select>
            </div>
            <div className="ef-row">
              <div className="ef">
                <label>Цена (₸)</label>
                <input type="number" min="0" step="1" value={price} onChange={e => setPrice(e.target.value)} />
              </div>
              <div className="ef">
                <label>Единица</label>
                <select value={unit} onChange={e => setUnit(e.target.value)}>
                  <option value="шт">шт</option><option value="кг">кг</option>
                  <option value="л">л</option><option value="м">м</option>
                  <option value="пара">пара</option><option value="комплект">комплект</option>
                </select>
              </div>
            </div>
            <div className="ef-row">
              <div className="ef">
                <label>Телефон</label>
                <input value={phone} onChange={e => setPhone(e.target.value)} placeholder="+7 700 000 0000" />
              </div>
              <div className="ef">
                <label>Город</label>
                <input value={city} onChange={e => setCity(e.target.value)} placeholder="Алматы" />
              </div>
            </div>
            <button className="btn-save" type="submit" disabled={loading}>{loading ? 'Сохраняю...' : 'Сохранить изменения'}</button>
          </form>
        </div>
      </div>
    </>
  )
}
