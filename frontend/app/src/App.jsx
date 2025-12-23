import { BrowserRouter, Routes, Route } from "react-router-dom";
import { useEffect, useState } from "react";
import api from "./api/api";
import Layout from "./components/Layout";
import Home from "./pages/Home";
import Unauthorized from "./pages/Unauthorized";

function App() {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.get("/me")
      .then((res) => {
        setUser(res.data);
        setLoading(false);
      })
      .catch(() => {});
  }, []);

  if (loading) return <div>Loading...</div>;

  return (
    <BrowserRouter>
      <Layout user={user}>
        <Routes>
          <Route path="/" element={<Home user={user} />} />
          <Route path="/unauthorized" element={<Unauthorized />} />
          <Route path="/admin" element={<Admin />} />
        </Routes>
      </Layout>
    </BrowserRouter>
  );
}

export default App;
