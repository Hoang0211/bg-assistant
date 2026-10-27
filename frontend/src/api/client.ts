import createClient from "openapi-fetch";
import type { paths } from "@/api/schema";

export const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// Typed client for the backend API; paths and responses come from the generated schema.
export const api = createClient<paths>({
  baseUrl: API_URL,
  // Look up fetch on every call, so test tools that replace it (MSW in Node) are picked up.
  fetch: (request) => globalThis.fetch(request),
});
