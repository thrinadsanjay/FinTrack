import { useEffect, useState } from "react";
import api from "../api/api";

// function Home() {
//   const [user, setUser] = useState(null);

//   useEffect(() => {
//     api.get("/me").then((res) => {
//       setUser(res.data);
//     });
//   }, []);

//   if (!user) return null;

//   return (
//     <div>
//       <h2>Welcome, {user.username}</h2>

//       <p>Roles: {user.roles.join(", ")}</p>

//       {user.roles.includes("admin") && (
//         <button>Admin Console</button>
//       )}

//       <br /><br />

//       <button onClick={() => window.location.href = "/api/logout"}>
//         Logout
//       </button>
//     </div>
//   );
// }

function Home({ user }) {
  return (
    <div>
      <h2>Dashboard</h2>

      <p><strong>User:</strong> {user.username}</p>
      <p><strong>Roles:</strong> {user.roles.join(", ")}</p>
    </div>
  );
}

export default Home;
