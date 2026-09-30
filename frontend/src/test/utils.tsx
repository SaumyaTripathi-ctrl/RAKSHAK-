import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { vi } from "vitest";

import { AuthProvider } from "@/lib/auth";
import { setToken } from "@/lib/api";
import { ThemeProvider } from "@/lib/theme";
import type { Role, User } from "@/lib/types";

export interface Call {
  method: string;
  path: string;
  query: Record<string, string>;
  body: unknown;
  auth: string | null;
}

type Handler = unknown | ((c: Call) => unknown);

/** Route table: keys are "METHOD /path" or "/path" (any method). Unknown routes answer 404. */
export function mockApi(routes: Record<string, Handler>): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), "http://localhost");
      const method = (init?.method ?? "GET").toUpperCase();
      const headers = (init?.headers ?? {}) as Record<string, string>;
      const call: Call = {
        method,
        path: url.pathname,
        query: Object.fromEntries(url.searchParams),
        body: init?.body ? JSON.parse(String(init.body)) : undefined,
        auth: headers.Authorization ?? null,
      };
      calls.push(call);
      const h = routes[`${method} ${url.pathname}`] ?? routes[url.pathname];
      if (h === undefined) return new Response(JSON.stringify({ detail: `no mock for ${method} ${url.pathname}` }), { status: 404 });
      const val = typeof h === "function" ? (h as (c: Call) => unknown)(call) : h;
      if (val instanceof Response) return val;
      return new Response(JSON.stringify(val), { status: 200, headers: { "content-type": "application/json" } });
    }),
  );
  return calls;
}

export const USERS: Record<Role, User> = {
  admin: { username: "admin", role: "admin", full_name: "Asha Admin", organisation: "Rakshak Ops", language: "en" },
  fpo: { username: "fpo", role: "fpo", full_name: "Ramesh Patil", organisation: "Konkan Hapus FPO", language: "hi" },
  driver: { username: "driver", role: "driver", full_name: "Sunil Jadhav", organisation: "Sahyadri Transport", language: "hi" },
  exporter: { username: "exporter", role: "exporter", full_name: "Meera Shah", organisation: "Fresh Exports", language: "en" },
};

export function renderPage(
  ui: ReactElement,
  opts: { path?: string; route?: string; role?: Role | null; routes?: Record<string, Handler> } = {},
) {
  const role = opts.role === undefined ? "admin" : opts.role;
  const routes: Record<string, Handler> = { ...(opts.routes ?? {}) };
  if (role) {
    setToken("test-token");
    routes["GET /api/auth/me"] ??= USERS[role];
  }
  const calls = mockApi(routes);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0, refetchInterval: false } } });
  const path = opts.path ?? "/";
  const utils = render(
    <ThemeProvider>
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={[opts.route ?? path.replace(/:(\w+)\??/g, "X")]}>
          <AuthProvider>
            <Routes>
              <Route path={path} element={ui} />
              <Route path="*" element={<div data-testid="elsewhere" />} />
            </Routes>
          </AuthProvider>
        </MemoryRouter>
      </QueryClientProvider>
    </ThemeProvider>,
  );
  return { ...utils, calls, client };
}
