import { useEffect, useState } from "react";
import { supabase } from "./supabase";
import { api } from "./api";
import Workspace from "./components/Workspace.jsx";
import GraphExplorer from "./components/GraphExplorer.jsx";
import Benchmarks from "./components/Benchmarks.jsx";

export default function App() {
  const [session, setSession] = useState(null);
  const [ready, setReady] = useState(false);
  const [tab, setTab] = useState("workspace");
  const [me, setMe] = useState(null);
  const [docs, setDocs] = useState([]);
  const [selected, setSelected] = useState([]);
  const [lastGraph, setLastGraph] = useState(null);
  const [nameError, setNameError] = useState("");

  useEffect(() => {
    supabase.auth.getSession().then(({ data }) => { setSession(data.session); setReady(true); });
    const { data } = supabase.auth.onAuthStateChange((_e, s) => setSession(s));
    return () => data.subscription.unsubscribe();
  }, []);

  useEffect(() => { if (session) api.me().then(setMe).catch(() => {}); }, [session]);

  const signIn = () =>
    supabase.auth.signInWithOAuth({ provider: "google", options: { redirectTo: window.location.origin } });

  async function saveUsername() {
    const name = window.prompt("Choose a username (3 to 30 characters)", me?.username || "");
    if (!name) return;
    try { await api.setUsername(name); setMe({ ...me, username: name }); setNameError(""); }
    catch (e) { setNameError(e.message); }
  }

  if (!ready) return null;
  if (!session)
    return (
      <div className="center">
        <h1>Medical GraphRAG</h1>
        <p className="muted">Sign in with your Google account to access your workspace.</p>
        <button className="primary" onClick={signIn}>Sign in with Google</button>
      </div>
    );

  const display = me?.username || session.user.user_metadata?.full_name || session.user.email;
  return (
    <>
      <header>
        <h1>Medical GraphRAG</h1>
        <nav>
          {[["workspace", "Workspace"], ["graph", "Graph Explorer"], ["bench", "Benchmarks"]].map(([k, label]) => (
            <button key={k} className={tab === k ? "active" : ""} onClick={() => setTab(k)}>{label}</button>
          ))}
        </nav>
        <span className="muted">{display}</span>
        <button className="link" onClick={saveUsername}>Edit username</button>
        <button className="link" onClick={() => supabase.auth.signOut()}>Sign out</button>
      </header>
      {nameError && <div className="err" style={{ padding: "0 24px" }}>{nameError}</div>}
      <main>
        {tab === "workspace" && (
          <Workspace docs={docs} setDocs={setDocs} selected={selected} setSelected={setSelected} setLastGraph={setLastGraph} />
        )}
        {tab === "graph" && <GraphExplorer docs={docs} selected={selected} highlight={lastGraph} />}
        {tab === "bench" && <Benchmarks docs={docs} selected={selected} />}
      </main>
    </>
  );
}
