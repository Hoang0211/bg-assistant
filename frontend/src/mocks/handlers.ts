import { delay, http, HttpResponse } from "msw";
import { API_URL } from "@/api/client";
import type { HealthResponse } from "@/api/types";

const healthUrl = `${API_URL}/api/health`;

/** Mock responses for `GET /api/health`, one per state the UI handles. */
export const healthHandlers = {
  ok: http.get(healthUrl, () =>
    HttpResponse.json<HealthResponse>({ status: "ok", database: "ok" }),
  ),
  degraded: http.get(healthUrl, () =>
    HttpResponse.json<HealthResponse>(
      { status: "degraded", database: "unreachable" },
      { status: 503 },
    ),
  ),
  unreachable: http.get(healthUrl, () => HttpResponse.error()),
  checking: http.get(healthUrl, async () => {
    await delay("infinite");
    return HttpResponse.json<HealthResponse>({ status: "ok", database: "ok" });
  }),
};

/** Default handlers: everything healthy. */
export const handlers = [healthHandlers.ok];
