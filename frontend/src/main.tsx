import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";

import App from "./App";
import { Unauthenticated } from "./api/client";
import { applyStoredTheme } from "./theme";

import "./styles/tokens.css";
import "./styles/base.css";
import "./styles/components.css";

applyStoredTheme();

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // A screen the user just navigated back to should not flash stale data,
      // but nor should every mount re-fetch what we read two seconds ago.
      staleTime: 10_000,
      refetchOnWindowFocus: false,
      retry: (failureCount, error) => {
        // Never retry an auth failure: the token is gone, and three more
        // attempts just produce three more 401s and a slower redirect to login.
        if (error instanceof Unauthenticated) return false;
        return failureCount < 2;
      },
    },
    mutations: { retry: false },
  },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
