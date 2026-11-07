import { useEffect, useState } from "react";
import { supabase } from "./supabase";
import { api } from "./api";
import Workspace from "./components/Workspace.jsx";
import GraphExplorer from "./components/GraphExplorer.jsx";
import Benchmarks from "./components/Benchmarks.jsx";

// Root component: handles Google sign-in state, the header/tabs, and holds the state shared by all tabs
// (the paper library, the user's groups and which one is active, and the last answer's graph).
export default function App() {
  const [session, setSession] = useState(null);
  const [ready, setReady] = useState(false);
  const [tab, setTab] = useState("workspace");
  const [me, setMe] = useState(null);
  const [docs, setDocs] = useState([]);
  const [groups, setGroups] = useState([]);
  const [activeGroupId, setActiveGroupId] = useState(null);
  const [lastGraph, setLastGraph] = useState(null);
  const [nameError, setNameError] = useState("");
  const [groupsError, setGroupsError] = useState("");

  // On first load: read any existing Supabase session, then subscribe to sign-in/sign-out changes.
  // The returned function unsubscribes when the component unmounts.
  useEffect(() => {
    supabase.auth.getSession().then(({ data }) => { setSession(data.session); setReady(true); });
    const { data } = supabase.auth.onAuthStateChange((_e, s) => setSession(s));
    return () => data.subscription.unsubscribe();
  }, []);

  // Re-fetch the user's groups. The server never returns an empty list (it creates "Group 1").
  // A failure is shown under the header, since without groups nothing can be asked or graphed.
  const refreshGroups = () =>
    api.groups().then((gs) => { setGroups(gs); setGroupsError(""); })
      .catch((e) => setGroupsError(`Could not load your groups: ${e.message}`));

  // Once signed in, load the user's profile (custom username) and groups. A profile failure is
  // ignored; the Google name is the fallback.
  useEffect(() => {
    if (!session) return;
    api.me().then(setMe).catch(() => {});
    refreshGroups();
  }, [session]);

  // The active group defaults to the first one, and falls back to it if the chosen group disappears.
  const activeGroup = groups.find((g) => g.id === activeGroupId) || groups[0] || null;

  // Start the Google OAuth flow through Supabase and return to this site afterwards.
  const signIn = () =>
    supabase.auth.signInWithOAuth({ provider: "google", options: { redirectTo: window.location.origin } });

  // Ask for a custom username (3 to 30 chars, validated by the backend) and save it.
  // A rejected name is shown in the red banner under the header.
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
        <h1>KG RAG Engine</h1>
        <p className="muted">Sign in with your Google account to access your workspace.</p>
        <button className="primary" onClick={signIn}>Sign in with Google</button>
      </div>
    );

  // Name shown in the header: custom username, else Google full name, else email.
  const display = me?.username || session.user.user_metadata?.full_name || session.user.email;
  // Props every tab needs to read or switch the active group
  const groupProps = { groups, activeGroup, setActiveGroupId };
  return (
    <>
      <header>
        <h1>KG RAG Engine</h1>
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
      {groupsError && <div className="err" style={{ padding: "0 24px" }}>{groupsError}</div>}
      <main className={tab === "workspace" ? "fill" : ""}>
        {tab === "workspace" && (
          <Workspace docs={docs} setDocs={setDocs} {...groupProps} refreshGroups={refreshGroups} setLastGraph={setLastGraph} />
        )}
        {tab === "graph" && (
          <GraphExplorer docs={docs} setDocs={setDocs} {...groupProps} setGroups={setGroups}
                         refreshGroups={refreshGroups} highlight={lastGraph} />
        )}
        {tab === "bench" && <Benchmarks docs={docs} activeGroup={activeGroup} />}
      </main>
    </>
  );
}
