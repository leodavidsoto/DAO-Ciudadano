/**
 * DAO Ciudadana - Main Application Entry
 *
 * Routes:
 *   /            landing pública (EstamosDAO)
 *   /unete       onboarding flow (identity verification + SBT)
 *   /dashboard   citizen governance dashboard
 *
 * La landing pasó a ser la puerta de entrada: antes "/" abría directo el
 * flujo de verificación, sin explicar antes qué es la red. El CTA "ÚNETE A
 * LA RED" es el que entra al onboarding, ahora en /unete.
 */
import React from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { OnboardingProvider } from "./context";
import { WalletSessionProvider } from "./hooks";
import { LandingPage, OnboardingPage } from "./pages";
import {
  DashboardLayout,
  OverviewSection,
  ProposalsSection,
  ElectionsSection,
  DelegationSection,
  TreasurySection,
} from "./pages/DashboardPage";
import "./App.css";
import "./styles/premium.css";

const App = () => {
  return (
    <BrowserRouter>
      <WalletSessionProvider>
        <div className="App">
          <Routes>
            <Route path="/" element={<LandingPage />} />

            {/* Onboarding keeps its own provider: the dashboard does not need
                the onboarding state machine and should not re-mount it. */}
            <Route
              path="/unete"
              element={
                <OnboardingProvider>
                  <OnboardingPage appearance="civic" />
                </OnboardingProvider>
              }
            />
            <Route
              path="/unete/clave-unica/callback"
              element={
                <OnboardingProvider>
                  <OnboardingPage appearance="civic" />
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
      </WalletSessionProvider>
    </BrowserRouter>
  );
};

export default App;
