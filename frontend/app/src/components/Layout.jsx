import { Link } from "react-router-dom";

function Layout({ user, children }) {
  return (
    <div>
      <header style={styles.header}>
        <div style={styles.left}>
          <strong>FinTracker</strong>
        </div>

        <nav style={styles.nav}>
          <Link to="/" style={styles.link}>Home</Link>

          {user?.roles.includes("admin") && (
            <Link to="/admin" style={styles.link}>Admin</Link>
          )}
        </nav>

        <div style={styles.right}>
          <span style={styles.user}>
            {user?.username}
          </span>
          <button
            style={styles.logout}
            onClick={() => window.location.href = "/api/logout"}
          >
            Logout
          </button>
        </div>
      </header>

      <main style={styles.main}>
        {children}
      </main>
    </div>
  );
}

const styles = {
  header: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    padding: "10px 20px",
    borderBottom: "1px solid #333",
  },
  left: {
    fontSize: "18px",
  },
  nav: {
    display: "flex",
    gap: "15px",
  },
  link: {
    textDecoration: "none",
    color: "#61dafb",
  },
  right: {
    display: "flex",
    gap: "10px",
    alignItems: "center",
  },
  user: {
    opacity: 0.8,
  },
  logout: {
    cursor: "pointer",
  },
  main: {
    padding: "20px",
  },
};

export default Layout;
