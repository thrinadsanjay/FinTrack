import axios from "axios";

const api = axios.create({
  baseURL: "/api",
  withCredentials: true, // 🔑 send session cookies
});

// Global auth handling
api.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err.response) {
      if (err.response.status === 401) {
        // Not logged in → backend login
        window.location.href = "/api/login";
      }
      if (err.response.status === 403) {
        window.location.href = "/unauthorized";
      }
    }
    return Promise.reject(err);
  }
);

export default api;
