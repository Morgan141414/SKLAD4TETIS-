const WS_URL = 'wss://127.0.0.1:13579/'
const MODULE = 'kz.gov.pki.ncalayer.sign'
const BROWSE_TIMEOUT = 180_000 // 3 min — user selects file & enters password
const OP_TIMEOUT = 30_000

export class NCALayerError extends Error {
  code: string
  constructor(message: string, code = 'UNKNOWN') {
    super(message)
    this.code = code
  }
}

export interface NCAKeyInfo {
  alias: string
  subjectDn: string
  subjectCn: string
  notBefore?: string
  notAfter?: string
}

interface Pending {
  method: string
  resolve: (v: any) => void
  reject: (e: Error) => void
  timer: ReturnType<typeof setTimeout>
}

class NCALayerClient {
  private ws: WebSocket | null = null
  private pending: Pending | null = null

  async connect(): Promise<void> {
    if (this.ws?.readyState === WebSocket.OPEN) return
    this.ws = null
    return new Promise((resolve, reject) => {
      let ws: WebSocket
      try {
        ws = new WebSocket(WS_URL)
      } catch {
        reject(new NCALayerError('NCALayer недоступен. Установите и запустите NCALayer.', 'NOT_INSTALLED'))
        return
      }
      const timer = setTimeout(() => {
        ws.close()
        reject(new NCALayerError('Timeout подключения к NCALayer', 'TIMEOUT'))
      }, 8000)
      ws.onopen = () => {
        clearTimeout(timer)
        this.ws = ws
        resolve()
      }
      ws.onerror = () => {
        clearTimeout(timer)
        reject(new NCALayerError('Не удалось подключиться к NCALayer. Убедитесь, что NCALayer запущен.', 'CONNECTION_FAILED'))
      }
      ws.onmessage = (event) => this.handleMessage(event)
      ws.onclose = () => {
        this.ws = null
        if (this.pending) {
          const p = this.pending
          this.pending = null
          clearTimeout(p.timer)
          p.reject(new NCALayerError('Соединение с NCALayer закрыто', 'DISCONNECTED'))
        }
      }
    })
  }

  private handleMessage(event: MessageEvent) {
    if (!this.pending) return
    let msg: any
    try { msg = JSON.parse(event.data as string) } catch { return }
    if (msg.method !== this.pending.method) return

    clearTimeout(this.pending.timer)
    const { resolve, reject } = this.pending
    this.pending = null

    const ec = String(msg.errorCode ?? msg.code ?? '')
    if (ec && ec !== '0' && ec !== '200') {
      reject(new NCALayerError(msg.errorMessage || this.errorMsg(ec), ec))
    } else {
      resolve(msg.result ?? msg.body ?? null)
    }
  }

  private errorMsg(code: string): string {
    const map: Record<string, string> = {
      WRONG_PASSWORD: 'Неверный пароль ЭЦП',
      CANCELLED: 'Операция отменена',
      NOT_FOUND: 'Сертификат не найден',
      EXPIRED: 'Срок действия сертификата истёк',
    }
    return map[code] || `Ошибка NCALayer: ${code}`
  }

  private send<T>(method: string, args: Record<string, unknown> = {}, timeout = OP_TIMEOUT): Promise<T> {
    return new Promise((resolve, reject) => {
      if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
        reject(new NCALayerError('Нет соединения с NCALayer', 'NOT_CONNECTED'))
        return
      }
      if (this.pending) {
        reject(new NCALayerError('NCALayer занят другой операцией', 'BUSY'))
        return
      }
      const timer = setTimeout(() => {
        this.pending = null
        reject(new NCALayerError('Превышено время ожидания NCALayer', 'TIMEOUT'))
      }, timeout)
      this.pending = { method, resolve, reject, timer }
      this.ws.send(JSON.stringify({ module: MODULE, method, args }))
    })
  }

  async getActiveTokens(): Promise<string[]> {
    const result = await this.send<any>('getActiveTokens', {}, 5000)
    if (Array.isArray(result)) return result
    if (result && typeof result === 'object') return Object.values(result).filter(Boolean) as string[]
    return ['PKCS12']
  }

  async browseKeyStore(storageName = 'PKCS12', password = ''): Promise<string> {
    return this.send<string>('browseKeyStore', { storageName, fileExtension: 'P12', password }, BROWSE_TIMEOUT)
  }

  async getKeyList(storageName: string): Promise<NCAKeyInfo[]> {
    const result = await this.send<any>('getKeyList', { storageName }, 10000)
    if (!result) return []
    const arr = Array.isArray(result) ? result : [result]
    return arr.map((item: any) => {
      if (typeof item === 'string') return { alias: item, subjectDn: item, subjectCn: item }
      return {
        alias: item.alias ?? item,
        subjectDn: item.subjectDn ?? item.alias ?? '',
        subjectCn: extractCN(item.subjectDn ?? item.alias ?? ''),
        notBefore: item.notBefore,
        notAfter: item.notAfter,
      }
    })
  }

  async signPlainData(selectedStore: string, alias: string, dataBase64: string): Promise<string> {
    return this.send<string>('signPlainData', {
      selectedStore,
      alias,
      data: dataBase64,
      signingParams: { tsaProfile: {} },
    })
  }

  isConnected(): boolean {
    return this.ws?.readyState === WebSocket.OPEN
  }

  disconnect() {
    this.ws?.close()
    this.ws = null
  }
}

function extractCN(dn: string): string {
  const m = dn.match(/CN=([^,]+)/i)
  return m ? m[1].trim() : dn
}

export function toBase64(str: string): string {
  return btoa(unescape(encodeURIComponent(str)))
}

export const ncaLayer = new NCALayerClient()
