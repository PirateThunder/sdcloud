"use client";

import { LoginForm } from "@/features/auth/ui/LoginForm";

export default function LoginPage() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-neutral-950 px-4">
      <div className="w-full max-w-md">
        <div className="mb-8 text-center">
          <h1 className="text-3xl font-bold text-white">sdCloud</h1>
          <p className="mt-2 text-neutral-400">
            AI-ассистент для системной динамики
          </p>
        </div>
        <LoginForm />
      </div>
    </div>
  );
}
