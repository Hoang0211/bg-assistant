import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { HealthStatus } from "@/features/health/health-status";
import { healthHandlers } from "@/mocks/handlers";
import { server } from "@/mocks/server";

function renderHealthStatus() {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <HealthStatus />
    </QueryClientProvider>,
  );
}

describe("HealthStatus", () => {
  it("shows that everything is up when the backend reports ok", async () => {
    renderHealthStatus();
    expect(await screen.findByText("Backend and database are up.")).toBeInTheDocument();
  });

  it("shows the database as unreachable when the backend answers 503", async () => {
    server.use(healthHandlers.degraded);
    renderHealthStatus();
    expect(
      await screen.findByText("Backend is up, but the database is unreachable."),
    ).toBeInTheDocument();
  });

  it("shows the backend URL when the backend can't be reached", async () => {
    server.use(healthHandlers.unreachable);
    renderHealthStatus();
    expect(await screen.findByText(/Can't reach the backend/)).toHaveTextContent(
      "http://localhost:8000",
    );
  });

  it("shows a checking message before the first answer", () => {
    server.use(healthHandlers.checking);
    renderHealthStatus();
    expect(screen.getByText("Checking the backend…")).toBeInTheDocument();
  });
});
