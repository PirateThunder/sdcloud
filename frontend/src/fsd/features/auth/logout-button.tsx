'use client'

import { LogOut } from 'lucide-react'
import { useRouter } from 'next/navigation'

import { logout } from '@/fsd/entities/session/api/auth-api'
import { useSession } from '@/fsd/entities/session/model/session-store'
import { Button } from '@/fsd/shared/ui/button'

export function LogoutButton() {
  const router = useRouter()
  const signOut = async () => {
    try {
      await logout()
    } catch {
      // The local session is cleared even if the server is unavailable.
    } finally {
      useSession.getState().clear()
      router.replace('/login')
    }
  }
  return (
    <Button
      type="button"
      variant="ghost"
      size="icon-sm"
      onClick={() => void signOut()}
      aria-label="Выйти"
    >
      <LogOut />
    </Button>
  )
}
