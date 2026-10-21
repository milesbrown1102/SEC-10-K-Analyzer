import { lazy, Suspense } from "react";
import { Link, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import { LoadingCards } from "./components/ui";
import Overview from "./pages/Overview";

const Industries = lazy(() => import("./pages/Industries"));
const Company = lazy(() => import("./pages/Company"));
const SmartMoney = lazy(() => import("./pages/SmartMoney"));
const Radar = lazy(() => import("./pages/Radar"));
const Scanner = lazy(() => import("./pages/Scanner"));
const TrackRecord = lazy(() => import("./pages/TrackRecord"));

export default function App() {
  return (
    <Layout>
      <Suspense fallback={<LoadingCards />}>
        <Routes>
          <Route path="/" element={<Overview />} />
          <Route path="/industries" element={<Industries />} />
          <Route path="/company/:ticker" element={<Company />} />
          <Route path="/smart-money" element={<SmartMoney />} />
          <Route path="/radar" element={<Radar />} />
          <Route path="/scanner" element={<Scanner />} />
          <Route path="/track-record" element={<TrackRecord />} />
          <Route path="*" element={<div className="card card-pad">Page not found. <Link to="/" className="link">Go to overview</Link></div>} />
        </Routes>
      </Suspense>
    </Layout>
  );
}
