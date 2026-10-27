import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { HealthStatus } from "@/features/health/health-status";
import { healthHandlers } from "@/mocks/handlers";

const meta = {
  title: "Features/HealthStatus",
  component: HealthStatus,
} satisfies Meta<typeof HealthStatus>;

export default meta;
type Story = StoryObj<typeof meta>;

/** Backend and database are up (the default handlers). */
export const Ok: Story = {};

/** The backend answers 503: the database is unreachable. */
export const Degraded: Story = {
  beforeEach({ msw }) {
    msw.use(healthHandlers.degraded);
  },
};

/** The backend doesn't answer at all. */
export const Unreachable: Story = {
  beforeEach({ msw }) {
    msw.use(healthHandlers.unreachable);
  },
};

/** No answer yet: the request never finishes, so the loading state stays visible. */
export const Checking: Story = {
  beforeEach({ msw }) {
    msw.use(healthHandlers.checking);
  },
};
