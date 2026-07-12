import { useEffect, useState, useRef, useCallback } from 'react'
import { useSearchParams } from 'react-router-dom'
import ProductCard, { type Product } from '../components/ProductCard'
import { apiBrowseCatalog, apiGetCategories } from '../api'

const PAGE = 24

const css = `
.catalog-wrap { max-width:1280px; margin:0 auto; padding:24px 20px 48px; }
.hero { display:grid; grid-template-columns:minmax(0,1.35fr) minmax(300px,.85fr); gap:24px; align-items:stretch; background:linear-gradient(135deg,#1E1B4B 0%,#4338CA 55%,#0EA5E9 100%); border-radius:22px; padding:38px; margin-bottom:14px; color:#fff; position:relative; overflow:hidden; }
.hero::before { content:''; position:absolute; right:-60px; top:-70px; width:310px; height:310px; background:rgba(255,255,255,.08); border-radius:50%; }
.hero-eyebrow { position:relative; display:inline-flex; align-items:center; min-height:28px; padding:4px 11px; border-radius:999px; background:rgba(255,255,255,.14); border:1px solid rgba(255,255,255,.18); font-size:12px; font-weight:800; letter-spacing:.8px; text-transform:uppercase; margin-bottom:14px; }
.hero h1 { font-size:40px; font-weight:900; margin-bottom:12px; letter-spacing:-.5px; line-height:1.12; position:relative; max-width:720px; }
.hero p { font-size:16px; opacity:.9; position:relative; max-width:700px; line-height:1.6; }
.hero-actions { position:relative; display:flex; gap:10px; flex-wrap:wrap; margin-top:22px; }
.hero-primary, .hero-secondary { min-height:44px; display:inline-flex; align-items:center; justify-content:center; padding:0 18px; border-radius:12px; font-size:14px; font-weight:800; text-decoration:none; }
.hero-primary { background:#fff; color:#312E81; }
.hero-secondary { background:rgba(255,255,255,.12); color:#fff; border:1px solid rgba(255,255,255,.26); }
.hero-stats { position:relative; display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:10px; }
.hero-stat { min-height:88px; border-radius:14px; border:1px solid rgba(255,255,255,.18); background:rgba(255,255,255,.12); backdrop-filter:blur(8px); padding:14px; display:grid; align-content:center; gap:6px; }
.hero-stat span { color:rgba(255,255,255,.74); font-size:12px; font-weight:700; }
.hero-stat strong { font-size:22px; line-height:1.1; }
.trust-strip { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:10px; margin-bottom:20px; }
.trust-item { min-height:58px; display:flex; align-items:center; gap:10px; padding:11px 13px; border:1px solid #DCE5F3; background:#fff; border-radius:14px; color:#334155; font-size:13px; font-weight:700; box-shadow:0 8px 24px rgba(15,23,42,.04); }
.trust-dot { width:10px; height:10px; border-radius:999px; background:linear-gradient(135deg,#10B981,#3B82F6); flex-shrink:0; }
.cats-strip { display:flex; gap:8px; overflow-x:auto; padding-bottom:4px; margin-bottom:20px; scrollbar-width:none; -webkit-overflow-scrolling:touch; }
.cats-strip::-webkit-scrollbar { display:none; }
.cat-chip { flex-shrink:0; padding:8px 18px; border-radius:22px; border:1.5px solid #E2E8F0; background:#fff; font-size:13px; font-weight:600; color:#475569; cursor:pointer; transition:all .18s; white-space:nowrap; }
.cat-chip:hover { border-color:#5B4FE8; color:#5B4FE8; }
.cat-chip.active { background:var(--brand-grad); border-color:transparent; color:#fff; }
.toolbar { display:grid; grid-template-columns:auto minmax(220px,1fr) minmax(180px,220px); align-items:center; gap:12px; margin-bottom:20px; padding:12px; border:1px solid #E2E8F0; border-radius:16px; background:#fff; box-shadow:0 8px 24px rgba(15,23,42,.04); }
.results-count { font-size:14px; color:#94A3B8; }
.sort-sel { height:40px; padding:0 12px; border:1.5px solid #E2E8F0; border-radius:10px; font-size:13px; font-weight:600; color:#475569; background:#fff; outline:none; }
.sort-sel:focus { border-color:#5B4FE8; }
.price-filter { display:flex; align-items:center; gap:8px; }
.price-input { width:100%; height:40px; padding:0 10px; border:1.5px solid #E2E8F0; border-radius:10px; font-size:13px; font-weight:600; color:#475569; background:#fff; outline:none; }
.price-input:focus { border-color:#5B4FE8; }
.grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(240px,1fr)); gap:18px; }
.loading { display:flex; flex-direction:column; align-items:center; justify-content:center; padding:80px 0; color:#94A3B8; gap:14px; }
.spinner { width:36px; height:36px; border:3px solid #E2E8F0; border-top-color:#5B4FE8; border-radius:50%; animation:spin .7s linear infinite; }
@keyframes spin { to{transform:rotate(360deg)} }
.skeleton { background:#F1F5F9; border-radius:16px; overflow:hidden; }
.skel-img { background:#E2E8F0; aspect-ratio:4/3; animation:pulse 1.4s ease-in-out infinite; }
.skel-line { background:#E2E8F0; border-radius:4px; margin:10px 14px 0; animation:pulse 1.4s ease-in-out infinite; }
@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.4} }
.empty { text-align:center; padding:80px 0; color:#94A3B8; }
.empty h3 { font-size:18px; font-weight:700; color:#475569; margin-bottom:8px; }
.phone-modal { position:fixed; inset:0; background:rgba(15,15,35,.6); z-index:500; display:flex; align-items:center; justify-content:center; padding:16px; }
.phone-box { background:#fff; border-radius:20px; padding:32px; max-width:360px; width:100%; text-align:center; box-shadow:0 24px 64px rgba(0,0,0,.18); }
.phone-box h3 { font-size:18px; font-weight:800; color:#1E1B4B; margin-bottom:6px; }
.phone-number { font-size:26px; font-weight:800; color:#5B4FE8; letter-spacing:1px; margin:16px 0; }
.no-phone { font-size:14px; color:#94A3B8; margin:16px 0; }
.pagination { display:flex; align-items:center; justify-content:center; gap:8px; margin-top:36px; }
.pg-btn { width:38px; height:38px; border-radius:10px; border:1.5px solid #E2E8F0; background:#fff; font-size:14px; font-weight:700; color:#475569; cursor:pointer; display:flex; align-items:center; justify-content:center; transition:all .18s; }
.pg-btn:hover:not(:disabled) { border-color:#5B4FE8; color:#5B4FE8; }
.pg-btn.active { background:var(--brand-grad); border-color:transparent; color:#fff; }
.pg-btn:disabled { opacity:.4; cursor:not-allowed; }
.pg-info { font-size:14px; color:#94A3B8; padding:0 8px; }
@media(max-width:900px) { .hero{grid-template-columns:1fr} .trust-strip{grid-template-columns:repeat(2,minmax(0,1fr))} .toolbar{grid-template-columns:1fr 1fr} .results-count{grid-column:1/-1} }
@media(max-width:640px) { .hero{padding:24px 18px} .hero h1{font-size:27px} .hero-stats,.trust-strip,.toolbar{grid-template-columns:1fr} .price-filter{display:none} }
`

interface PhoneModal { name: string; phone: string | null }

function SkeletonCard() {
  return (
    <div className="skeleton">
      <div className="skel-img" />
      <div className="skel-line" style={{height:16,marginTop:14}} />
      <div className="skel-line" style={{height:12,width:'60%'}} />
      <div className="skel-line" style={{height:20,width:'40%',marginBottom:14}} />
    </div>
  )
}

export default function CatalogPage() {
  const [params, setParams] = useSearchParams()
  const q = params.get('search') || ''
  const catParam = params.get('cat') || ''

  const [products, setProducts] = useState<Product[]>([])
  const [total, setTotal] = useState(0)
  const [categories, setCategories] = useState<string[]>([])
  const [activeCat, setActiveCat] = useState<string>(catParam)
  const [sort, setSort] = useState('name')
  const [minPrice, setMinPrice] = useState('')
  const [maxPrice, setMaxPrice] = useState('')
  const [page, setPage] = useState(0)
  const [loading, setLoading] = useState(true)
  const [phoneModal, setPhoneModal] = useState<PhoneModal | null>(null)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    apiGetCategories().then(setCategories)
  }, [])

  const load = useCallback(() => {
    setLoading(true)
    apiBrowseCatalog({
      search: q || undefined,
      category: activeCat || undefined,
      sort: sort || undefined,
      min_price: minPrice ? parseFloat(minPrice) : undefined,
      max_price: maxPrice ? parseFloat(maxPrice) : undefined,
      limit: PAGE,
      offset: page * PAGE,
    }).then(r => {
      setProducts(r.items)
      setTotal(r.total)
    }).catch(() => {}).finally(() => setLoading(false))
  }, [q, activeCat, sort, minPrice, maxPrice, page])

  useEffect(() => {
    setPage(0)
  }, [q, activeCat, sort])

  useEffect(() => {
    if (timerRef.current) clearTimeout(timerRef.current)
    timerRef.current = setTimeout(load, 150)
    return () => { if (timerRef.current) clearTimeout(timerRef.current) }
  }, [load])

  function selectCat(c: string) {
    setActiveCat(prev => prev === c ? '' : c)
    const np = new URLSearchParams(params)
    if (c && activeCat !== c) np.set('cat', c); else np.delete('cat')
    setParams(np)
  }

  const totalPages = Math.ceil(total / PAGE)

  return (
    <>
      <style>{css}</style>
      <div className="catalog-wrap">
        {!q && (
          <div className="hero">
            <div>
              <div className="hero-eyebrow">marqet.kz marketplace</div>
              <h1>Маркетплейс для покупок, поставок и прямых заказов по Казахстану</h1>
              <p>Каталог товаров, проверенные продавцы, быстрые заявки, корзина и прозрачные условия покупки в одном рабочем пространстве.</p>
              <div className="hero-actions">
                <a className="hero-primary" href="#catalog-results">Перейти к товарам</a>
                <a className="hero-secondary" href="/post">Стать продавцом</a>
              </div>
            </div>
            <div className="hero-stats" aria-label="Показатели marketplace">
              <div className="hero-stat"><span>Активных товаров</span><strong>{loading ? '...' : total.toLocaleString('ru-KZ')}</strong></div>
              <div className="hero-stat"><span>Категорий</span><strong>{categories.length || '—'}</strong></div>
              <div className="hero-stat"><span>Сценарии</span><strong>B2C + B2B</strong></div>
              <div className="hero-stat"><span>География</span><strong>Казахстан</strong></div>
            </div>
          </div>
        )}
        {!q && (
          <div className="trust-strip" aria-label="Преимущества marqet.kz">
            <div className="trust-item"><span className="trust-dot" /> Проверенные продавцы и профили</div>
            <div className="trust-item"><span className="trust-dot" /> Корзина, заявки и сообщения</div>
            <div className="trust-item"><span className="trust-dot" /> Рассрочный сценарий готов к подключению</div>
            <div className="trust-item"><span className="trust-dot" /> Интеграция с qpartner складом</div>
          </div>
        )}

        <div className="cats-strip">
          <button className={`cat-chip ${!activeCat ? 'active' : ''}`} onClick={() => selectCat('')}>Все</button>
          {categories.slice(0, 20).map(c => (
            <button key={c} className={`cat-chip ${activeCat === c ? 'active' : ''}`} onClick={() => selectCat(c)}>{c}</button>
          ))}
        </div>

        <div className="toolbar">
          <span className="results-count">{loading ? '...' : `${total} ${total === 1 ? 'товар' : total < 5 ? 'товара' : 'товаров'}`}</span>
          <div className="price-filter">
            <input className="price-input" placeholder="от ₸" value={minPrice} onChange={e => setMinPrice(e.target.value)} type="number" min="0" />
            <span style={{color:'#CBD5E1'}}>—</span>
            <input className="price-input" placeholder="до ₸" value={maxPrice} onChange={e => setMaxPrice(e.target.value)} type="number" min="0" />
          </div>
          <select className="sort-sel" value={sort} onChange={e => setSort(e.target.value)}>
            <option value="name">По названию</option>
            <option value="price_asc">Сначала дешевле</option>
            <option value="price_desc">Сначала дороже</option>
          </select>
        </div>

        {loading ? (
          <div className="grid">{Array.from({length: 8}).map((_, i) => <SkeletonCard key={i} />)}</div>
        ) : products.length === 0 ? (
          <div className="empty">
            <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="#CBD5E1" strokeWidth="1.5" style={{marginBottom:12}}><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/></svg>
            <h3>Ничего не найдено</h3>
            <p>{q ? `По запросу «${q}» нет товаров` : 'В этой категории пока нет товаров'}</p>
            {activeCat && <button className="cat-chip" onClick={() => selectCat('')} style={{marginTop:12}}>Сбросить фильтр</button>}
          </div>
        ) : (
          <>
            <div className="grid" id="catalog-results">
              {products.map(p => (
                <ProductCard key={p.id} p={p} onContact={prod => setPhoneModal({ name: prod.supplier_name || 'Продавец', phone: prod.supplier_phone })} />
              ))}
            </div>

            {totalPages > 1 && (
              <div className="pagination">
                <button className="pg-btn" onClick={() => setPage(p => p - 1)} disabled={page === 0}>‹</button>
                {Array.from({length: Math.min(totalPages, 7)}).map((_, i) => {
                  const p = totalPages <= 7 ? i : (page < 4 ? i : page - 3 + i)
                  if (p < 0 || p >= totalPages) return null
                  return (
                    <button key={p} className={`pg-btn ${p === page ? 'active' : ''}`} onClick={() => { setPage(p); window.scrollTo(0,0) }}>
                      {p + 1}
                    </button>
                  )
                })}
                <button className="pg-btn" onClick={() => setPage(p => p + 1)} disabled={page >= totalPages - 1}>›</button>
                <span className="pg-info">{page + 1} / {totalPages}</span>
              </div>
            )}
          </>
        )}
      </div>

      {phoneModal && (
        <div className="phone-modal" onClick={() => setPhoneModal(null)}>
          <div className="phone-box" onClick={e => e.stopPropagation()}>
            <h3>{phoneModal.name}</h3>
            {phoneModal.phone ? <div className="phone-number">{phoneModal.phone}</div> : <div className="no-phone">Номер не указан</div>}
            <button onClick={() => setPhoneModal(null)} style={{padding:'10px 28px',borderRadius:12,background:'#EEF2FF',color:'#5B4FE8',fontWeight:700,fontSize:14,border:'none',cursor:'pointer'}}>Закрыть</button>
          </div>
        </div>
      )}
    </>
  )
}
