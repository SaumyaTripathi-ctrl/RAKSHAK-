import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Suspense, lazy } from "react";
import { BrowserRouter, Link, Route, Routes } from "react-router-dom";

import { Layout } from "@/components/Layout";
import { LoadingBlock } from "@/components/States";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api";
import { AuthProvider, RequireAuth } from "@/lib/auth";
import { ThemeProvider } from "@/lib/theme";

import Login from "./pages/Login";

const Fleet = lazy(() => import("./pages/Fleet"));
const Shipments = lazy(() => import("./pages/Shipments"));
const ShipmentDetail = lazy(() => import("./pages/ShipmentDetail"));
const Alerts = lazy(() => import("./pages/Alerts"));
const Custody = lazy(() => import("./pages/Custody"));
const Verify = lazy(() => import("./pages/Verify"));
const Devices = lazy(() => import("./pages/Devices"));
const SimulatorControl = lazy(() => import("./pages/SimulatorControl"));
const PublicQr = lazy(() => import("./pages/PublicQr"));

export function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 5_000,
        refetchOnWindowFocus: false,
        retry: (count, err) => !(err instanceof ApiError && err.status >= 400 && err.status < 500) && count < 2,
      },
    },
  });
}

function NotFound() {
  return (
    <div className="flex min-h-[50vh] flex-col items-center justify-center gap-3 text-center">
      <p className="text-5xl font-bold">404</p>
      <Button asChild>
        <Link to="/">Rakshak</Link>
      </Button>
    </div>
  );
}

export function AppRoutes() {
  return (
    <Suspense fallback={<div className="p-6"><LoadingBlock rows={3} /></div>}>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/p/:id" element={<PublicQr />} />
        <Route
          element={
            <RequireAuth>
              <Layout />
            </RequireAuth>
          }
        >
          <Route index element={<Fleet />} />
          <Route path="shipments" element={<Shipments />} />
          <Route path="shipments/:id" element={<ShipmentDetail />} />
          <Route path="alerts" element={<Alerts />} />
          <Route path="alerts/:id" element={<Alerts />} />
          <Route path="custody" element={<Custody />} />
          <Route path="custody/:id" element={<Custody />} />
          <Route path="verify" element={<Verify />} />
          <Route path="verify/:id" element={<Verify />} />
          <Route
            path="devices"
            element={
              <RequireAuth roles={["admin", "fpo"]}>
                <Devices />
              </RequireAuth>
            }
          />
          <Route
            path="simulator"
            element={
              <RequireAuth roles={["admin"]}>
                <SimulatorControl />
              </RequireAuth>
            }
          />
          <Route path="*" element={<NotFound />} />
        </Route>
      </Routes>
    </Suspense>
  );
}

export default function App() {
  const client = makeQueryClient();
  return (
    <ThemeProvider>
      <QueryClientProvider client={client}>
        <BrowserRouter>
          <AuthProvider>
            <AppRoutes />
          </AuthProvider>
        </BrowserRouter>
      </QueryClientProvider>
    </ThemeProvider>
  );
}
