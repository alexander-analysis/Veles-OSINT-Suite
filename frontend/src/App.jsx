import { Suspense, lazy } from 'react';
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import Navigation from './components/common/Navigation';
import ClassificationBanner from './components/common/ClassificationBanner';
import ErrorBoundary from './components/common/ErrorBoundary';
import LoadingSpinner from './components/common/LoadingSpinner';
import { useFetch } from './hooks/useFetch';

// Pages are code-split so the map/chart libraries load only when needed.
const Dashboard = lazy(() => import('./pages/Dashboard'));
const MarketAnalysis = lazy(() => import('./pages/MarketAnalysis'));
const Maritime = lazy(() => import('./pages/Maritime'));
const VesselDetail = lazy(() => import('./pages/VesselDetail'));
const Sanctions = lazy(() => import('./pages/Sanctions'));
const Correlation = lazy(() => import('./pages/Correlation'));
const Geopolitical = lazy(() => import('./pages/Geopolitical'));
const Blockchain = lazy(() => import('./pages/Blockchain'));
const Corporate = lazy(() => import('./pages/Corporate'));
const Energy = lazy(() => import('./pages/Energy'));
const Fusion = lazy(() => import('./pages/Fusion'));
const AuditLogPage = lazy(() => import('./pages/AuditLogPage'));
const Settings = lazy(() => import('./pages/Settings'));

function App() {
  const { data: config } = useFetch('/api/admin/config', 0);
  const marking = config?.classification?.banner;

  return (
    <BrowserRouter>
      <div className="min-h-screen bg-cream flex flex-col">
        <ClassificationBanner level={marking} />
        <Navigation />
        <main className="container mx-auto p-6 flex-1 w-full">
          <ErrorBoundary>
            <Suspense fallback={<LoadingSpinner label="Loading" />}>
              <Routes>
                <Route path="/" element={<Dashboard />} />
                <Route path="/market" element={<MarketAnalysis />} />
                <Route path="/maritime" element={<Maritime />} />
                <Route path="/maritime/vessel/:mmsi" element={<VesselDetail />} />
                <Route path="/sanctions" element={<Sanctions />} />
                <Route path="/geopolitical" element={<Geopolitical />} />
                <Route path="/blockchain" element={<Blockchain />} />
                <Route path="/corporate" element={<Corporate />} />
                <Route path="/energy" element={<Energy />} />
                <Route path="/fusion" element={<Fusion />} />
                <Route path="/correlation" element={<Correlation />} />
                <Route path="/audit" element={<AuditLogPage />} />
                <Route path="/settings" element={<Settings />} />
              </Routes>
            </Suspense>
          </ErrorBoundary>
        </main>
        <footer className="border-t border-gray-200 bg-white text-xs text-gray-500 no-print">
          <div className="container mx-auto px-6 py-3 flex flex-wrap gap-x-6 gap-y-1 justify-between">
            <span>VELES OSINT Intelligence Platform</span>
            <span>
              Data: Binance, Kraken, Coinbase, Yahoo Finance; AIS: Fintraffic Digitraffic (CC BY 4.0) and configured providers; OFAC SDN, EU consolidated list,
              UN Security Council list; GDELT Project, UK FCDO, UN press, OFAC; Blockstream, PublicNode, Tronscan, blockchain.com; GLEIF, SEC EDGAR; &copy; OpenStreetMap contributors
            </span>
          </div>
        </footer>
        <ClassificationBanner level={marking} />
      </div>
    </BrowserRouter>
  );
}

export default App;
