import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { RequireLogin } from "./auth";
import { ROUTER_BASENAME } from "./lib/base";
import { AppShell } from "./components/AppShell";
import { Climate } from "./pages/Climate";
import { Energy } from "./pages/Energy";
import { Login } from "./pages/Login";
import { MapPage } from "./pages/MapPage";
import { Notifications } from "./pages/Notifications";
import { Overview } from "./pages/Overview";
import { Panel } from "./pages/Panel";
import { Settings } from "./pages/Settings";
import { Changelog } from "./pages/Changelog";
import { HeaterSetup } from "./pages/HeaterSetup";
import { Sensors } from "./pages/Sensors";
import { Setup } from "./pages/Setup";
import { SwitchDetail } from "./pages/SwitchDetail";
import { Switches } from "./pages/Switches";
import { System } from "./pages/System";
import { VictronSetup } from "./pages/VictronSetup";

export function App() {
  return (
    <BrowserRouter basename={ROUTER_BASENAME || undefined}>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/setup" element={<Setup />} />
        {/* Full-screen instrument panel for a tablet in the van: no navigation. */}
        <Route
          path="/panel"
          element={
            <RequireLogin>
              <Panel />
            </RequireLogin>
          }
        />
        <Route
          element={
            <RequireLogin>
              <AppShell />
            </RequireLogin>
          }
        >
          <Route index element={<Overview />} />
          <Route path="energy" element={<Energy />} />
          <Route path="energy/devices" element={<VictronSetup />} />
          <Route path="climate" element={<Climate />} />
          <Route path="climate/heaters" element={<HeaterSetup />} />
          <Route path="switches" element={<Switches />} />
          <Route path="switches/:id" element={<SwitchDetail />} />
          <Route path="map" element={<MapPage />} />
          <Route path="sensors" element={<Sensors />} />
          <Route path="notifications" element={<Notifications />} />
          <Route path="settings" element={<Settings />} />
          <Route path="system" element={<System />} />
          <Route path="changelog" element={<Changelog />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
