import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import App from "./App.jsx";
import { AuthProvider } from "./auth.jsx";
import AdminPage from "./pages/AdminPage.jsx";
import ChatPage from "./pages/ChatPage.jsx";
import DocumentsPage from "./pages/DocumentsPage.jsx";
import LoginPage from "./pages/LoginPage.jsx";
import StaffingPage from "./pages/StaffingPage.jsx";
import LeaveLedgerPage from "./pages/LeaveLedgerPage.jsx";
import "./styles.css";

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route element={<App />}>
            <Route index element={<ChatPage />} />
            <Route path="documents" element={<DocumentsPage />} />
            <Route path="staffing" element={<StaffingPage />} />
            <Route path="leave-ledger" element={<LeaveLedgerPage />} />
            {/* 考勤汇总台账暂缓：页面文件缺失会导致整站白屏 */}
            <Route path="attendance-summary" element={<Navigate to="/" replace />} />
            <Route path="attendance" element={<Navigate to="/" replace />} />
            <Route path="admin" element={<AdminPage />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  </React.StrictMode>,
);
