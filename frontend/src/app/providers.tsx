"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";

/** Client-side providers shared by every page; currently the TanStack Query client. */
export function Providers({ children }: { children: ReactNode }) {
  // One QueryClient per browser session; useState keeps the same one across re-renders.
  const [queryClient] = useState(() => new QueryClient());
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}
