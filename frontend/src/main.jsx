import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import App from "./App.jsx";
import { AuthProvider } from "./auth.jsx";
import AdminPage from "./pages/AdminPage.jsx";
import ChatPage from "./pages/ChatPage.jsx";
import DocumentsPage from "./pages/DocumentsPage.jsx";
import LoginPage from "./pages/LoginPage.jsx";
import StaffingPage from "./pages/StaffingPage.jsx";
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
            <Route path="admin" element={<AdminPage />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  </React.StrictMode>,
);
