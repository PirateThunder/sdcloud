import type { NextConfig } from 'next'

const backendUrl = process.env.BACKEND_URL ?? 'http://localhost:61231'

const nextConfig: NextConfig = {
  reactCompiler: true,
  distDir: 'dist',
  rewrites() {
    return [{ source: '/api/:path*', destination: `${backendUrl}/api/:path*` }]
  },
}

export default nextConfig
