"use client";

import { useQuery } from "@tanstack/react-query";
import { API_URL, api } from "@/api/client";
import { cn } from "@/lib/utils";
import type { HealthResponse } from "@/api/types";

/** Fetch the health status. A 503 still returns its body; only an unreachable backend throws. */
async function fetchHealth(): Promise<HealthResponse> {
  const { data, error } = await api.GET("/api/health");
  const body = data ?? error;
  if (!body) throw new Error("The backend sent an empty health response.");
  return body;
}

/** Live backend and database status; polls `/api/health` every 5 seconds. */
export function HealthStatus() {
  const { data, isPending, isError } = useQuery({
    queryKey: ["health"],
    queryFn: fetchHealth,
    refetchInterval: 5000,
    retry: false,
  });

  const { label, dotClass } = isPending
    ? { label: "Checking the backend…", dotClass: "bg-muted-foreground" }
    : isError
      ? { label: `Can't reach the backend at ${API_URL}.`, dotClass: "bg-red-500" }
      : data.status === "ok"
        ? { label: "Backend and database are up.", dotClass: "bg-green-500" }
        : { label: "Backend is up, but the database is unreachable.", dotClass: "bg-amber-500" };

  return (
    <p role="status" aria-live="polite" className="flex items-center gap-2 text-sm">
      <span aria-hidden="true" className={cn("size-2 rounded-full", dotClass)} />
      {label}
    </p>
  );
}
