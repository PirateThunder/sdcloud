import ky, { type KyInstance } from 'ky'

import { getSession } from '@/fsd/entities/session/model/session-store'
import { authResponseSchema } from '@/fsd/entities/session/model/types'

const bareKy = ky.create({ retry: 0, timeout: 30_000 })
let refreshPromise: Promise<boolean> | null = null

export function refreshSession(): Promise<boolean> {
  if (!refreshPromise) {
    refreshPromise = (async () => {
      try {
        const data = await bareKy.post('/api/v1/auth/refresh', { credentials: 'include' }).json()
        const parsed = authResponseSchema.parse(data)
        getSession().setToken(parsed.access_token, parsed.expires_in)
        getSession().setUser(parsed.user)
        return true
      } catch {
        getSession().clear()
        return false
      } finally {
        setTimeout(() => {
          refreshPromise = null
        }, 0)
      }
    })()
  }
  return refreshPromise
}

export const api: KyInstance = ky.create({
  prefix: '/api/v1',
  credentials: 'include',
  retry: { limit: 2, shouldRetry: () => false },
  timeout: 60_000,
  hooks: {
    beforeRequest: [
      ({ request }) => {
        const { accessToken } = getSession()
        if (accessToken) request.headers.set('Authorization', `Bearer ${accessToken}`)
      },
    ],
    afterResponse: [
      async ({ request, response, retryCount }) => {
        if (response.status !== 401) return
        if (new URL(request.url).pathname.includes('/auth/')) return
        if (retryCount > 0) return
        if (!(await refreshSession())) return
        const { accessToken } = getSession()
        const headers = new Headers(request.headers)
        if (accessToken) headers.set('Authorization', `Bearer ${accessToken}`)
        return ky.retry({ request: new Request(request, { headers }), code: 'TOKEN_REFRESHED' })
      },
    ],
    beforeError: [
      async ({ error }) => {
        const response = (error as { response?: Response }).response
        if (!response) return error
        try {
          const body = (await response.clone().json()) as {
            error?: { message?: string }
            detail?: string | Array<{ msg?: string }>
          }
          const message = body?.error?.message ?? body?.detail
          if (typeof message === 'string' && message) error.message = message
          else if (Array.isArray(message)) error.message = 'Проверьте поля запроса'
        } catch {
          // Keep the original HTTP error for non-JSON responses.
        }
        return error
      },
    ],
  },
})

export async function downloadAuthedFile(path: string, filename: string): Promise<void> {
  const blob = await api.get(path).blob()
  const objectUrl = URL.createObjectURL(blob)
  try {
    const anchor = document.createElement('a')
    anchor.href = objectUrl
    anchor.download = filename
    document.body.append(anchor)
    anchor.click()
    anchor.remove()
  } finally {
    setTimeout(() => URL.revokeObjectURL(objectUrl), 10_000)
  }
}
