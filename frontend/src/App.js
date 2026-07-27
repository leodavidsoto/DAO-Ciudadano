/**
 * DAO Ciudadana - Main Application Entry
 *
 * Routes:
 *   /            onboarding flow (identity verification + SBT)
 *   /dashboard   citizen governance dashboard
 */
import React, { useEffect } from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { OnboardingProvider } from "./context";
import { OnboardingPage } from "./pages";
import {
  DashboardLayout,
  OverviewSection,
  ProposalsSection,
  ElectionsSection,
  DelegationSection,
  TreasurySection,
} from "./pages/DashboardPage";
import { warmUpBackend } from "./lib/api";
import "./App.css";
import "./styles/premium.css";

const App = () => {
  // The API sleeps on the free tier. Start waking it as soon as the app
  // mounts so the first real request does not pay the full boot time.
  useEffect(() => {
    warmUpBackend();
  }, []);

  return (
    <BrowserRouter>
      <div className="App">
        <Routes>
          {/* Onboarding keeps its own provider: the dashboard does not need
              the onboarding state machine and should not re-mount it. */}
          <Route
            path="/"
            element={
              <OnboardingProvider>
                <OnboardingPage />
              </OnboardingProvider>
            }
          />

          <Route path="/dashboard" element={<DashboardLayout />}>
            <Route index element={<OverviewSection />} />
            <Route path="propuestas" element={<ProposalsSection />} />
            <Route path="elecciones" element={<ElectionsSection />} />
            <Route path="delegacion" element={<DelegationSection />} />
            <Route path="tesoreria" element={<TreasurySection />} />
          </Route>

          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </div>
    </BrowserRouter>
  );
};

export default App;
