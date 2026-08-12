import { Navigate, Route, Routes } from 'react-router-dom';

import { ChargerDetail } from './pages/ChargerDetail';
import { DataOperations } from './pages/DataOperations';

export function App() {
  return (
    <Routes>
      <Route path="/" element={<Navigate to="/data-operations" replace />} />
      <Route path="/data-operations" element={<DataOperations />} />
      <Route path="/chargers/:chargerId" element={<ChargerDetail />} />
      <Route
        path="*"
        element={
          <div className="app">
            <div className="panel">
              <div className="empty">Page not found.</div>
            </div>
          </div>
        }
      />
    </Routes>
  );
}
