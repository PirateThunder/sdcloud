import type { ReactNode } from 'react'

import { Providers } from '@/fsd/app/providers/providers'
import '@/fsd/app/styles/globals.css'

export function RootShell({ children }: { children: ReactNode }) {
  return (
    <html lang="ru" data-theme="light" suppressHydrationWarning className="h-full antialiased">
      <head>
        <script
          // biome-ignore lint/security/noDangerouslySetInnerHtml: static pre-hydration theme script
          dangerouslySetInnerHTML={{
            __html: `(function(){try{var t=localStorage.getItem("sdcloud-theme");if(t==="light"||t==="dark")document.documentElement.setAttribute("data-theme",t)}catch(e){}})()`,
          }}
        />
      </head>
      <body className="min-h-full">
        <Providers>{children}</Providers>
      </body>
    </html>
  )
}
