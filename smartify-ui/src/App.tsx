

import { Toaster } from "@/components/ui/toaster";
import { Toaster as Sonner } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";

import Login from "./pages/Login";
import DashboardLayout from "./layouts/DashboardLayout";
import OverviewDashboard from "./pages/dashboard/OverviewDashboard";
import GpsDashboard from "./pages/dashboard/GpsDashboard";
import EnergyDashboard from "./pages/dashboard/EnergyDashboard";
import RelaysDashboard from "./pages/dashboard/RelaysDashboard";
import SettingsDashboard from "./pages/dashboard/SettingsDashboard";
import TemperatureDashboard from "./pages/dashboard/TemperatureDashboard";
import DbIntegrityDashboard from "./pages/dashboard/DbIntegrityDashboard";

import NotFound from "./pages/NotFound";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      retry: 1,
      staleTime: 1000, // Consider data stale after 1s
    },
  },
});

const App = () => (
  <QueryClientProvider client={queryClient}>
    <TooltipProvider>
      <div className="dark">
        <Toaster />
        <Sonner />
        <BrowserRouter>
          <Routes>
            <Route path="/login" element={<Login />} />

            <Route path="/dashboard" element={<DashboardLayout />}>
              {/* MAIN DASHBOARD OVERVIEW */}
              <Route index element={<OverviewDashboard />} />

              {/* Tabs */}
              <Route path="gps" element={<GpsDashboard />} />
              <Route path="energy" element={<EnergyDashboard />} />
<Route path="temperature" element={<TemperatureDashboard />} />
              <Route path="relays" element={<RelaysDashboard />} />
              <Route path="settings" element={<SettingsDashboard />} />
              <Route path="system/db" element={<DbIntegrityDashboard />} />

            </Route>

            {/* Root goes to dashboard overview */}
            <Route path="/" element={<Navigate to="/dashboard" replace />} />

            <Route path="*" element={<NotFound />} />
          </Routes>
        </BrowserRouter>
      </div>
    </TooltipProvider>
  </QueryClientProvider>
);

export default App;
