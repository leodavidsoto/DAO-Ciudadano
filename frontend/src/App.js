/**
 * DAO Ciudadana - Main Application Entry
 * 
 * Professional modular React application with premium UI
 */
import React from "react";
import { OnboardingProvider } from "./context";
import { OnboardingPage } from "./pages";
import "./App.css";
import "./styles/premium.css";

/**
 * Main App Component
 * 
 * Wraps the application with necessary providers and renders the main page.
 * Future: Add React Router here for multiple pages (governance, profile, etc.)
 */
const App = () => {
  return (
    <OnboardingProvider>
      <div className="App">
        <OnboardingPage />
      </div>
    </OnboardingProvider>
  );
};

export default App;