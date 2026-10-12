import { createRoot } from "react-dom/client";
import "../../src/styles.css";
import { AuthProvider, useAuth } from "../../src/auth/AuthProvider";
import { AuthRoute } from "../../src/auth/AuthPages";
function Content() {
  const {state} = useAuth();
  if (state.status === "loading") return <p>Checking access</p>;
  if (state.status === "authenticated") return <p role="status">Signed in as {state.session.email}</p>;
  const pathname = window.location.pathname;
  return <AuthRoute
    location={{pathname,search:window.location.search,hash:""}} />;
}
createRoot(document.getElementById("root")!).render(<AuthProvider><Content /></AuthProvider>);
