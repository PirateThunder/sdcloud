"use client";

import React, { useState } from "react";
import Link from "next/link";
import { Button } from "@/shared/ui/button";
import { Input } from "@/shared/ui/input";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
} from "@/shared/ui/card";
import { Label } from "@/shared/ui/label";
import { useRegister } from "../api";
import { useAuthStore } from "../model";
import { UserPlus } from "lucide-react";

export function RegisterForm() {
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [validationError, setValidationError] = useState<string | null>(null);
  const register = useRegister();
  const { isLoading, error } = useAuthStore();

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setValidationError(null);

    if (!username.trim() || !email.trim() || !password.trim()) {
      setValidationError("Заполните все обязательные поля");
      return;
    }

    if (password !== confirmPassword) {
      setValidationError("Пароли не совпадают");
      return;
    }

    if (password.length < 6) {
      setValidationError("Пароль должен содержать минимум 6 символов");
      return;
    }

    register.mutate({ username, email, password });
  };

  const displayError = validationError || error;

  return (
    <Card className="w-full max-w-md border-border/50">
      <CardHeader className="space-y-1">
        <CardTitle className="text-2xl font-bold text-center">
          Регистрация в sdCloud
        </CardTitle>
        <CardDescription className="text-center">
          Создайте новый аккаунт
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="username">Имя пользователя</Label>
            <Input
              id="username"
              type="text"
              placeholder="Введите имя пользователя"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
              className="bg-background"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="email">Email</Label>
            <Input
              id="email"
              type="email"
              placeholder="Введите email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              className="bg-background"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="password">Пароль</Label>
            <Input
              id="password"
              type="password"
              placeholder="Минимум 6 символов"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              className="bg-background"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="confirmPassword">Подтвердите пароль</Label>
            <Input
              id="confirmPassword"
              type="password"
              placeholder="Повторите пароль"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              required
              className="bg-background"
            />
          </div>
          {displayError && (
            <div className="text-sm text-destructive bg-destructive/10 p-3 rounded-md">
              {displayError}
            </div>
          )}
          <Button type="submit" className="w-full" disabled={isLoading}>
            {isLoading ? (
              "Регистрация..."
            ) : (
              <>
                <UserPlus className="mr-2 h-4 w-4" />
                Зарегистрироваться
              </>
            )}
          </Button>
          <div className="text-center text-sm text-muted-foreground">
            Уже есть аккаунт?{" "}
            <Link
              href="/login"
              className="text-primary hover:underline font-medium"
            >
              Войти
            </Link>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}
