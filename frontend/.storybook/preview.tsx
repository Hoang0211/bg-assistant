import type { Preview } from "@storybook/nextjs-vite";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { mswLoader } from "msw-storybook-addon/csf3";
import "@/app/globals.css";
import { handlers } from "@/mocks/handlers";

const preview: Preview = {
  parameters: {
    controls: {
      matchers: {
        color: /(background|color)$/i,
        date: /Date$/i,
      },
    },

    a11y: {
      // Fail story tests on accessibility violations.
      test: "error",
    },
  },
  loaders: [mswLoader()],
  decorators: [
    (Story) => (
      <QueryClientProvider client={new QueryClient()}>
        <Story />
      </QueryClientProvider>
    ),
  ],
  beforeEach({ msw }) {
    msw.use(...handlers);
  },
};

export default preview;
