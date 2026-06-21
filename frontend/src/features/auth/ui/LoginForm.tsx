"use client";

import React, { useState } from "react";
import Link from "next/link";
import { Button } from "@/shared/ui/button";
import { Input } from "@/shared/ui/input";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/shared/ui/card";
import { Label } from "@/shared/ui/label";
import { useLogin } from "../api";
import { useAuthStore } from "../model";
import { LogIn } from "lucide-react";

export function LoginForm() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const login = useLogin();
  const { isLoading, error } = useAuthStore();

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!username.trim() || !password.trim()) return;
    login.mutate({ username, password });
  };

  return (
    <Card className="w-full max-w-md border-border/50">
      <CardHeader className="space-y-1">
        <CardTitle className="text-2xl font-bold text-center">
          Вход в sdCloud
        </CardTitle>
        <CardDescription className="text-center">
          Введите свои данные для входа
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
            <Label htmlFor="password">Пароль</Label>
            <Input
              id="password"
              type="password"
              placeholder="Введите пароль"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              className="bg-background"
            />
          </div>
          {error && (
            <div className="text-sm text-destructive bg-destructive/10 p-3 rounded-md">
              {error}
            </div>
          )}
          <Button type="submit" className="w-full" disabled={isLoading}>
            {isLoading ? (
              "Вход..."
            ) : (
              <>
                <LogIn className="mr-2 h-4 w-4" />
                Войти
              </>
            )}
          </Button>
          <div className="text-center text-sm text-muted-foreground">
            Нет аккаунта?{" "}
            <Link
              href="/register"
              className="text-primary hover:underline font-medium"
            >
              Зарегистрироваться
            </Link>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}
