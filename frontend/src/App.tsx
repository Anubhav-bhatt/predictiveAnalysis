import { Navigate, Route, Routes } from 'react-router-dom';

import { ChargerDetail } from './pages/ChargerDetail';
import { DataOperations } from './pages/DataOperations';
import { FleetResearchPage } from './pages/FleetResearchPage';
import { UploadBatchDetail } from './pages/UploadBatchDetail';
import { UploadData } from './pages/UploadData';
import { UploadHistory } from './pages/UploadHistory';

export function App() {
  return (
    <Routes>
      <Route path="/" element={<Navigate to="/data-operations" replace />} />
      <Route path="/data-operations" element={<DataOperations />} />
      <Route path="/data-operations/upload" element={<UploadData />} />
      <Route path="/data-operations/uploads" element={<UploadHistory />} />
      <Route path="/data-operations/uploads/:batchId" element={<UploadBatchDetail />} />
      <Route path="/chargers/:chargerId" element={<ChargerDetail />} />
      <Route path="/research" element={<FleetResearchPage />} />
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
