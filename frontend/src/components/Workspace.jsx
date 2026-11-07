import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import Answer from "./Answer.jsx";

/**
 * Workspace tab: upload PDFs to the library and ask questions over the active group.
 *
 * Layout (top to bottom, fills the window height - see ".workspace" in styles.css):
 *   1. Upload bar      - fixed height, file picker plus any upload message
 *   2. Library pane    - the ONLY part that grows and scrolls, so a long paper list never
 *                        pushes the prompt box off screen
 *   3. Answer pane     - appears only after the user asks something (answer, sources, graph path)
 *   4. Prompt bar      - pinned to the bottom: group picker, textbox, and the Ask button on the right
 *
 * Props (all state is owned by App.jsx so the other tabs can share it):
 *   docs             - the user's library (document records from the API)
 *   setDocs          - updates that list
 *   groups           - the user's groups
 *   activeGroup      - the group questions are asked over
 *   setActiveGroupId - switches the active group
 *   refreshGroups    - re-fetches groups (deleting a paper removes it from every group)
 *   setLastGraph     - hands the latest answer's graph to the Graph Explorer so it can highlight the path
 */
export default function Workspace({ docs, setDocs, groups, activeGroup, setActiveGroupId, refreshGroups, setLastGraph }) {
  const fileRef = useRef(null);            // hidden handle on the file input (kept for future use)
  const [msg, setMsg] = useState("");          // upload / list error shown in the upload bar
  const [question, setQuestion] = useState(""); // current text in the prompt box
  const [result, setResult] = useState(null);   // last answer returned by the backend
  const [busy, setBusy] = useState(false);      // true while a question is being answered
  const [qError, setQError] = useState("");     // error from the last question, if any

  // Re-fetch the library from the backend and store it in App's state.
  // Any failure is shown in the upload bar instead of crashing the page.
  const refresh = () => api.documents().then(setDocs).catch((e) => setMsg(e.message));

  // Load the list once when the tab first opens.
  useEffect(() => { refresh(); }, []);

  // While any paper is still 'processing', poll every 3 seconds so its state flips to
  // 'ready' or 'failed' without the user reloading. The timer is cleared as soon as nothing
  // is processing (or when the component unmounts), so we never poll for no reason.
  useEffect(() => {
    if (!docs.some((d) => d.status === "processing")) return;
    const t = setInterval(refresh, 3000);
    return () => clearInterval(t);
  }, [docs]);

  // Handle the user choosing a PDF. Flow: upload -> refresh list. If the backend answers 409
  // (same file hash already stored) we ask whether to replace it, and re-upload with the
  // override flag so the old index is rebuilt. Any other error goes to the upload bar.
  async function upload(e) {
    const file = e.target.files[0];
    e.target.value = ""; // reset the input so choosing the same file again still fires onChange
    if (!file) return;
    setMsg("");
    try { await api.upload(file); refresh(); }
    catch (err) {
      if (err.status === 409) {
        setMsg(err.message);
        if (window.confirm("This document already exists. Replace it and re-index?")) {
          try { await api.upload(file, true); setMsg(""); refresh(); } catch (e2) { setMsg(e2.message); }
        }
      } else setMsg(err.message);
    }
  }

  // Delete a paper from the library. The server also drops it from every group, so groups are
  // re-fetched too, otherwise the Graph Explorer would still count it as a member.
  async function remove(d) {
    if (!window.confirm(`Delete "${d.name}" from your library? It is also removed from every group.`)) return;
    try { await api.remove(d.id); await Promise.all([refresh(), refreshGroups()]); }
    catch (e) { setMsg(e.message); }
  }

  // Send the question and the active group's id to the backend.
  // Clears the previous answer first so stale results never sit next to a new question, then
  // stores the new answer and passes its graph up so the Graph Explorer can highlight the path.
  async function ask() {
    setBusy(true); setQError(""); setResult(null);
    try {
      const r = await api.query(question, activeGroup.id);
      setResult(r); setLastGraph(r.graph);
    } catch (e) { setQError(e.message); }
    setBusy(false);
  }

  // Keyboard shortcut for the prompt box: Enter sends the question, Shift+Enter inserts a
  // new line. isComposing is true while an IME (e.g. Japanese/Chinese input) is still choosing
  // characters, and Enter must not send in that case.
  function onPromptKeyDown(e) {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();       // stop the textarea from inserting a line break
      if (canAsk) ask();
    }
  }

  // Only ready papers of the active group can be searched.
  const members = new Set(activeGroup?.document_ids || []);
  const readyCount = docs.filter((d) => d.status === "ready" && members.has(d.id)).length;

  // The Ask button and the Enter shortcut share this one rule: not already working, a
  // question of at least 3 characters, and at least one ready paper in the active group.
  const canAsk = !busy && question.trim().length >= 3 && readyCount > 0;

  // Small helper line under the prompt. When Ask is disabled because the group has nothing
  // searchable we say why, instead of leaving the user with a silently greyed-out button.
  const hint = readyCount === 0
    ? "This group has no ready papers. Add ready papers to it in the Graph Explorer."
    : `${readyCount} ready paper(s) in this group`;

  // The answer pane is shown while waiting, on success, and on error.
  const showAnswerPane = busy || result || qError;

  return (
    <div className="workspace">
      {/* 1. Upload bar: fixed height at the top */}
      <section className="card upload-bar">
        <h2>Library</h2>
        <input ref={fileRef} type="file" accept="application/pdf" onChange={upload} />
        {msg && <div className="err">{msg}</div>}
      </section>

      {/* 2. Library pane: takes the leftover height and scrolls on its own */}
      <section className="card pane docs-pane">
        <div className="scroll">
          <table>
            <thead><tr><th>Name</th><th>State</th><th></th></tr></thead>
            <tbody>
              {docs.map((d) => (
                <tr key={d.id}>
                  <td>{d.name}</td>
                  <td>
                    <span className={`badge ${d.status}`}>{d.status}</span>
                    {d.status === "processing" && <div className="muted">{d.stage}</div>}
                    {d.status === "failed" && <div className="err">{d.error}</div>}
                  </td>
                  <td>
                    {d.status === "failed" && <button className="link" onClick={() => api.retry(d.id).then(refresh)}>Retry</button>}
                    <button className="link" onClick={() => remove(d)}>Delete</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {docs.length === 0 && <p className="muted">Your library is empty. Upload a PDF above.</p>}
        </div>
      </section>

      {/* 3. Answer pane: only present once a question has been asked; scrolls on its own */}
      {showAnswerPane && (
        <section className="card pane answer-pane">
          <h2>Answer</h2>
          <div className="scroll">
            {busy && <div className="muted">Retrieving context and generating an answer...</div>}
            {qError && <div className="err">{qError}</div>}
            {result && <Answer result={result} />}
          </div>
        </section>
      )}

      {/* 4. Prompt bar: pinned to the bottom, Ask button on the right of the textbox */}
      <section className="card prompt-bar">
        <div className="row prompt-group">
          <label className="muted" htmlFor="ask-group">Ask over group</label>
          <select id="ask-group" value={activeGroup?.id || ""} onChange={(e) => setActiveGroupId(e.target.value)}>
            {groups.map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}
          </select>
        </div>
        <div className="prompt-row">
          <textarea
            rows={2}
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={onPromptKeyDown}
            placeholder="Ask about the papers in this group (Enter to send, Shift+Enter for a new line)"
          />
          <button className="primary ask-btn" disabled={!canAsk} onClick={ask}>
            {busy ? "Working..." : "Ask"}
          </button>
        </div>
        <div className="muted prompt-hint">{hint}</div>
      </section>
    </div>
  );
}
