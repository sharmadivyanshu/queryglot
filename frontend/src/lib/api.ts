/**
 * Thin fetch wrappers over the serve-layer contracts. No response
 * interpretation lives here — engine outcomes (answered/abstained/failed)
 * pass through untouched; only a non-2xx HTTP response throws, so callers
 * have a single error path (network failure and non-ok status both reject).
 */

export type Outcome = 'answered' | 'abstained' | 'failed'

export interface SearchResponse {
  outcome: Outcome
  backend: string
  query: string
  result: unknown
  reason: string
  schema_used: string[]
  attempts: number
  elapsed_ms: number
}

export interface SchemaResponse {
  items: string[]
}

export interface StatusResponse {
  backends: Record<string, number>
  version: string
}

export interface ClientOptions {
  api: string
  token?: string
}

export interface Client {
  search(question: string, backend?: string): Promise<SearchResponse>
  schema(query?: string, limit?: number): Promise<SchemaResponse>
  status(): Promise<StatusResponse>
}

async function request<T>(url: string, token: string | undefined, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (token) {
    headers.Authorization = `Bearer ${token}`
  }
  const response = await fetch(url, { ...init, headers })
  const body = (await response.json()) as T
  if (!response.ok) {
    throw new Error(`request to ${url} failed with status ${response.status}`)
  }
  return body
}

export function createClient({ api, token }: ClientOptions): Client {
  return {
    search(question, backend) {
      return request<SearchResponse>(`${api}/api/search`, token, {
        method: 'POST',
        body: JSON.stringify({ question, backend }),
      })
    },
    schema(query = '', limit = 20) {
      const params = new URLSearchParams()
      if (query) {
        params.set('query', query)
      }
      params.set('limit', String(limit))
      return request<SchemaResponse>(`${api}/api/schema?${params.toString()}`, token)
    },
    status() {
      return request<StatusResponse>(`${api}/api/status`, token)
    },
  }
}
