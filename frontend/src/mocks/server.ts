import { setupServer } from "msw/node";
import { handlers } from "@/mocks/handlers";

/** MSW for tests that run in Node (Vitest's `unit` project). */
export const server = setupServer(...handlers);
