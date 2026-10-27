import type { components } from "@/api/schema";

/** Body of `GET /api/health`, for both the 200 and the 503 response. */
export type HealthResponse = components["schemas"]["HealthResponse"];
