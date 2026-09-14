import { BrowserRouter, Routes, Route } from 'react-router-dom';
import Navigation from './components/common/Navigation';
import ClassificationBanner from './components/common/ClassificationBanner';
import ErrorBoundary from './components/common/ErrorBoundary';
import Dashboard from './pages/Dashboard';
import MarketAnalysis from './pages/MarketAnalysis';
import Maritime from './pages/Maritime';
import Settings from './pages/Settings';

function App() {
  return (
    <BrowserRouter>
      <div className="min-h-screen bg-cream flex flex-col">
        <ClassificationBanner />
        <Navigation />
        <main className="container mx-auto p-6 flex-1 w-full">
          <ErrorBoundary>
            <Routes>
              <Route path="/" element={<Dashboard />} />
              <Route path="/market" element={<MarketAnalysis />} />
              <Route path="/maritime" element={<Maritime />} />
              <Route path="/settings" element={<Settings />} />
            </Routes>
          </ErrorBoundary>
        </main>
        <footer className="border-t border-gray-200 bg-white text-xs text-gray-500 no-print">
          <div className="container mx-auto px-6 py-3 flex flex-wrap gap-x-6 gap-y-1 justify-between">
            <span>VELES OSINT Intelligence Platform</span>
            <span>
              Data: Binance, Kraken, Coinbase, Yahoo Finance, AIS providers, OFAC / EU / UN sanctions lists,
              &copy; OpenStreetMap contributors
            </span>
          </div>
        </footer>
        <ClassificationBanner />
      </div>
    </BrowserRouter>
  );
}

export default App;
