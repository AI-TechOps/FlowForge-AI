/**
 * Test harness: a component under a router, a fresh QueryClient, and a chosen
 * identity.
 *
 * Retries off and no cache between tests — a component test that retries turns
 * an assertion about an error state into a three-second wait, and a shared
 * cache lets one test's data satisfy another's query.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import type { ReactElement } from "react";
import { vi } from "vitest";

import type { Identity, Role } from "../api/types";
import { IdentityProvider } from "../shell/Shell";

export function identityWith(...roles: Role[]): Identity {
  return {
    id: "11111111-1111-1111-1111-111111111111",
    org_id: "22222222-2222-2222-2222-222222222222",
    email: `${roles[0] ?? "none"}@demo`,
    roles,
  };
}

export function renderWith(
  ui: ReactElement,
  { identity = identityWith("administrator"), route = "/" } = {},
) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0, staleTime: 0 },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[route]}>
        <IdentityProvider value={identity}>{ui}</IdentityProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

/** Stubs `fetch` with a path -> response map. Unmapped paths fail loudly. */
export function stubFetch(routes: Record<string, unknown>, status = 200) {
  const impl = async (input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input.toString();
    const path = url.split("?")[0]!;
    if (!(path in routes)) {
      throw new Error(`unstubbed fetch: ${url}`);
    }
    return new Response(JSON.stringify(routes[path]), {
      status,
      headers: { "Content-Type": "application/json" },
    });
  };
  return vi.spyOn(globalThis, "fetch").mockImplementation(impl as typeof fetch);
}
