import { useEffect, useState, useRef } from 'react'
import { useParams, Link } from 'react-router-dom'
import type { Product } from '../components/ProductCard'
import ProductCard from '../components/ProductCard'
import { apiGetSellerProfile, type SellerProfile } from '../api'

const css = `
.sp { max-width:1280px; margin:0 auto; padding:28px 20px 60px; }
.sp-header { background:#fff; border-radius:20px; border:1px solid #E2E8F0; padding:32px; margin-bottom:24px; display:grid; grid-template-columns:auto 1fr auto; gap:24px; align-items:start; }
@media(max-width:640px){.sp-header{grid-template-columns:1fr;}}
.sp-av { width:80px; height:80px; border-radius:50%; background:linear-gradient(135deg,#5B4FE8,#3B82F6); color:#fff; font-size:32px; font-weight:900; display:flex; align-items:center; justify-content:center; flex-shrink:0; }
.sp-name { font-size:24px; font-weight:900; color:#1E1B4B; margin-bottom:8px; display:flex; align-items:center; gap:8px; }
.sp-verified { display:inline-flex; align-items:center; gap:4px; background:#D1FAE5; color:#059669; padding:3px 10px; border-radius:20px; font-size:11px; font-weight:800; }
.sp-badges { display:flex; flex-wrap:wrap; gap:8px; margin-bottom:12px; }
.sp-badge { display:flex; align-items:center; gap:5px; font-size:13px; padding:5px 12px; border-radius:20px; font-weight:600; }
.badge-city { background:#EEF2FF; color:#5B4FE8; }
.badge-joined { background:#F1F5F9; color:#64748B; }
.sp-contact { display:flex; flex-direction:column; gap:10px; align-items:flex-end; }
.sp-phone-btn { padding:12px 20px; border-radius:12px; background:linear-gradient(135deg,#5B4FE8,#3B82F6); color:#fff; font-weight:700; font-size:14px; border:none; cursor:pointer; white-space:nowrap; }
.sp-phone-btn:hover { opacity:.9; }
.sp-stats { display:grid; grid-template-columns:repeat(4,1fr); gap:12px; margin-bottom:24px; }
@media(max-width:640px){.sp-stats{grid-template-columns:repeat(2,1fr);}}
.sp-stat { background:#fff; border:1px solid #E2E8F0; border-radius:14px; padding:16px; text-align:center; }
.sp-stat-val { font-size:26px; font-weight:900; color:#5B4FE8; }
.sp-stat-lbl { font-size:12px; color:#94A3B8; margin-top:3px; font-weight:600; }
.sp-rating-block { background:#fff; border:1px solid #E2E8F0; border-radius:14px; padding:16px 20px; margin-bottom:24px; display:flex; align-items:center; gap:16px; }
.sp-rating-big { font-size:48px; font-weight:900; color:#1E1B4B; line-height:1; }
.sp-stars { font-size:22px; color:#F59E0B; margin-bottom:4px; }
.sp-rating-sub { font-size:13px; color:#64748B; }
.sp-map { margin-bottom:24px; border-radius:16px; overflow:hidden; border:1px solid #E2E8F0; height:200px; background:#F1F5F9; }
.sp-map iframe { width:100%; height:100%; border:0; }
.sp-map-placeholder { display:flex; align-items:center; justify-content:center; height:100%; color:#CBD5E1; flex-direction:column; gap:8px; font-size:13px; }
.sp-listings-title { font-size:18px; font-weight:800; color:#1E1B4B; margin-bottom:16px; }
.sp-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(240px,1fr)); gap:18px; }
.sp-empty { text-align:center; padding:40px; color:#94A3B8; }
.sp-member { display:inline-flex; align-items:center; gap:4px; }
`

function Stars({ rating, size = 18 }: { rating: number; size?: number }) {
  const full = Math.floor(rating)
  const half = rating - full >= 0.5
  return (
    <span style={{ fontSize: size, color: '#F59E0B', letterSpacing: 2 }}>
      {'★'.repeat(full)}{half ? '½' : ''}{'☆'.repeat(5 - full - (half ? 1 : 0))}
    </span>
  )
}

function Map({ city }: { city: string }) {
  const [coords, setCoords] = useState<{ lat: number; lon: number } | null>(null)
  const fetched = useRef(false)

  useEffect(() => {
    if (fetched.current) return
    fetched.current = true
    fetch(`https://nominatim.openstreetmap.org/search?q=${encodeURIComponent(city + ', Казахстан')}&format=json&limit=1`)
      .then(r => r.json())
      .then((res: any[]) => {
        if (res[0]) setCoords({ lat: parseFloat(res[0].lat), lon: parseFloat(res[0].lon) })
      })
      .catch(() => {})
  }, [city])

  if (!coords) {
    return (
      <div className="sp-map-placeholder">
        <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/><circle cx="12" cy="10" r="3"/></svg>
        <span>{city}</span>
      </div>
    )
  }

  const { lat, lon } = coords
  const delta = 0.05
  const bbox = `${lon - delta},${lat - delta},${lon + delta},${lat + delta}`
  const src = `https://www.openstreetmap.org/export/embed.html?bbox=${bbox}&layer=mapnik&marker=${lat},${lon}`

  return <iframe src={src} loading="lazy" title={`Карта ${city}`} />
}

function toProduct(r: any): Product {
  return {
    id: r.id,
    supplier_id: r.supplier_id,
    name: r.product_name,
    description: r.description ?? null,
    price: r.unit_price != null ? parseFloat(r.unit_price) : null,
    unit: r.unit ?? null,
    supplier_name: null,
    supplier_phone: null,
    image_url: r.image_url ?? null,
    category: r.category ?? null,
    avg_rating: r.avg_rating ?? null,
    review_count: r.review_count ?? null,
    likes_count: r.likes_count ?? null,
  }
}

export default function SellerPage() {
  const { id } = useParams<{ id: string }>()
  const [seller, setSeller] = useState<SellerProfile | null>(null)
  const [loading, setLoading] = useState(true)
  const [showPhone, setShowPhone] = useState(false)

  useEffect(() => {
    if (!id) return
    apiGetSellerProfile(parseInt(id))
      .then(s => setSeller(s))
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [id])

  if (loading) return <div style={{ textAlign: 'center', padding: 80, color: '#94A3B8' }}>Загрузка...</div>
  if (!seller) return <div style={{ textAlign: 'center', padding: 80, color: '#94A3B8' }}>Продавец не найден</div>

  const joinYear = seller.created_at ? new Date(seller.created_at).getFullYear() : null
  const listings: Product[] = (seller.listings || []).map(toProduct)

  return (
    <>
      <style>{css}</style>
      <div className="sp">
        <div className="sp-header">
          <div className="sp-av">{seller.name[0]?.toUpperCase()}</div>
          <div>
            <div className="sp-name">
              {seller.name}
              {seller.is_verified && <span className="sp-verified">✓ Проверен</span>}
            </div>
            <div className="sp-badges">
              {seller.city && (
                <span className="sp-badge badge-city">
                  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/><circle cx="12" cy="10" r="3"/></svg>
                  {seller.city}
                </span>
              )}
              {joinYear && (
                <span className="sp-badge badge-joined">
                  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>
                  На сайте с {joinYear}
                </span>
              )}
            </div>
          </div>
          <div className="sp-contact">
            {seller.phone && (
              <button className="sp-phone-btn" onClick={() => setShowPhone(true)}>
                {showPhone ? seller.phone : 'Показать телефон'}
              </button>
            )}
          </div>
        </div>

        <div className="sp-stats">
          <div className="sp-stat">
            <div className="sp-stat-val">{seller.active_listings}</div>
            <div className="sp-stat-lbl">Активных объявлений</div>
          </div>
          <div className="sp-stat">
            <div className="sp-stat-val">{seller.total_listings}</div>
            <div className="sp-stat-lbl">Всего объявлений</div>
          </div>
          <div className="sp-stat">
            <div className="sp-stat-val">{seller.total_reviews}</div>
            <div className="sp-stat-lbl">Отзывов</div>
          </div>
          <div className="sp-stat">
            <div className="sp-stat-val">{seller.seller_rating > 0 ? seller.seller_rating.toFixed(1) : '—'}</div>
            <div className="sp-stat-lbl">Рейтинг</div>
          </div>
        </div>

        {seller.seller_rating > 0 && (
          <div className="sp-rating-block">
            <div className="sp-rating-big">{seller.seller_rating.toFixed(1)}</div>
            <div>
              <div className="sp-stars"><Stars rating={seller.seller_rating} size={20} /></div>
              <div className="sp-rating-sub">{seller.total_reviews} {seller.total_reviews === 1 ? 'отзыв' : seller.total_reviews < 5 ? 'отзыва' : 'отзывов'}</div>
            </div>
          </div>
        )}

        {seller.city && (
          <div className="sp-map">
            <Map city={seller.city} />
          </div>
        )}

        <div className="sp-listings-title">
          Объявления продавца ({listings.length})
        </div>

        {listings.length === 0 ? (
          <div className="sp-empty">Нет активных объявлений</div>
        ) : (
          <div className="sp-grid">
            {listings.map(p => <ProductCard key={p.id} p={p} />)}
          </div>
        )}
      </div>
    </>
  )
}
