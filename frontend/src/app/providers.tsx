"use client";

import { QueryClientProvider } from "@tanstack/react-query";
import { queryClient } from "@/shared/api/query-client";
import { ReactNode } from "react";

export function Providers({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}
