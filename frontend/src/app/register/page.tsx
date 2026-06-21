"use client";

import { RegisterForm } from "@/features/auth/ui/RegisterForm";

export default function RegisterPage() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-neutral-950 px-4">
      <div className="w-full max-w-md">
        <div className="mb-8 text-center">
          <h1 className="text-3xl font-bold text-white">sdCloud</h1>
          <p className="mt-2 text-neutral-400">
            Создайте аккаунт для начала работы
          </p>
        </div>
        <RegisterForm />
      </div>
    </div>
  );
}
