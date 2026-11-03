import { fetchMe } from '@/fsd/entities/session/api/auth-api'
import { useSession } from '@/fsd/entities/session/model/session-store'
import { refreshSession } from '@/fsd/shared/api/http'

export async function bootstrapSession(): Promise<void> {
  if (useSession.getState().status === 'auth') return
  if (!(await refreshSession())) {
    useSession.getState().setAnonymous()
    return
  }
  try {
    const user = await fetchMe()
    useSession.setState({ user, status: 'auth' })
  } catch {
    useSession.getState().setAnonymous()
  }
}
