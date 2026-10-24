import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { HashRouter, Route, Routes } from "react-router-dom";
import { registerSW } from "virtual:pwa-register";
import { Layout } from "./components/Layout";
import { configured } from "./lib/supabase";
import { UserProvider } from "./lib/user";
import { ArchivePage } from "./pages/Archive";
import { EditionPage } from "./pages/Edition";
import { FrontPage } from "./pages/Front";
import { MyPaper } from "./pages/MyPaper";
import { NotConfigured } from "./pages/NotConfigured";
import { PrepPage } from "./pages/Prep";
import { SectionPage } from "./pages/Section";
import { StatusPage } from "./pages/Status";
import { StoryPage } from "./pages/Story";
import "./styles.css";

registerSW({ immediate: true });

function App() {
  if (!configured) return <NotConfigured />;
  return (
    <UserProvider>
      <HashRouter>
        <Layout>
          <Routes>
            <Route path="/" element={<FrontPage />} />
            <Route path="/edition" element={<EditionPage />} />
            <Route path="/edition/:date" element={<EditionPage />} />
            <Route path="/section/:slug" element={<SectionPage />} />
            <Route path="/story/:id" element={<StoryPage />} />
            <Route path="/archive" element={<ArchivePage />} />
            <Route path="/prep" element={<PrepPage />} />
            <Route path="/me" element={<MyPaper />} />
            <Route path="/status" element={<StatusPage />} />
            <Route path="*" element={<FrontPage />} />
          </Routes>
        </Layout>
      </HashRouter>
    </UserProvider>
  );
}

createRoot(document.getElementById("root")!).render(<StrictMode><App /></StrictMode>);
