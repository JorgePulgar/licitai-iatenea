import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider } from './hooks/useAuth';
import { ModalProvider } from './hooks/useModal';
import ProtectedRoute from './components/auth/ProtectedRoute';
import LoginPage from './pages/LoginPage';
import LicitacionesPage from './pages/LicitacionesPage';
import ColaProcesadoPage from './pages/ColaProcesadoPage';
import CreateLicitacionPage from './pages/CreateLicitacionPage';
import LicitacionDetailPage from './pages/LicitacionDetailPage';
import SettingsPage from './pages/SettingsPage';
import AuditPage from './pages/AuditPage';

export default function App() {
  return (
    <BrowserRouter>
      <ModalProvider>
        <AuthProvider>
          <Routes>
            <Route path="/" element={<Navigate to="/login" replace />} />
            <Route path="/login" element={<LoginPage />} />
            <Route
              path="/licitaciones"
              element={
                <ProtectedRoute>
                  <LicitacionesPage />
                </ProtectedRoute>
              }
            />
            <Route
              path="/cola-procesado"
              element={
                <ProtectedRoute>
                  <ColaProcesadoPage />
                </ProtectedRoute>
              }
            />
            <Route
              path="/licitaciones/nueva"
              element={
                <ProtectedRoute>
                  <CreateLicitacionPage />
                </ProtectedRoute>
              }
            />
            <Route
              path="/licitaciones/:id"
              element={
                <ProtectedRoute>
                  <LicitacionDetailPage />
                </ProtectedRoute>
              }
            />
            <Route
              path="/auditoria"
              element={
                <ProtectedRoute>
                  <AuditPage />
                </ProtectedRoute>
              }
            />
            <Route
              path="/settings"
              element={
                <ProtectedRoute>
                  <SettingsPage />
                </ProtectedRoute>
              }
            />
            <Route path="*" element={<Navigate to="/licitaciones" replace />} />
          </Routes>
        </AuthProvider>
      </ModalProvider>
    </BrowserRouter>
  );
}
