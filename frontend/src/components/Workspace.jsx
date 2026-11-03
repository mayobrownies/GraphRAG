import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import Answer from "./Answer.jsx";

/**
 * Workspace tab: upload PDFs, pick which ready documents to search, and ask questions.
 *
 * Layout (top to bottom, fills the window height - see ".workspace" in styles.css):
 *   1. Upload bar      - fixed height, file picker plus any upload message
 *   2. Documents pane  - the ONLY part that grows and scrolls, so a long document list never
 *                        pushes the prompt box off screen
 *   3. Answer pane     - appears only after the user asks something (answer, sources, graph path)
 *   4. Prompt bar      - pinned to the bottom, textbox on the left and the Ask button on the right
 *
 * Props (all state is owned by App.jsx so the other tabs can share it):
 *   docs         - list of document records from the API
 *   setDocs      - updates that list
 *   selected     - ids of the documents the user ticked for querying
 *   setSelected  - updates the selection
 *   setLastGraph - hands the latest answer's graph to the Graph Explorer so it can highlight the path
 */
export default function Workspace({ docs, setDocs, selected, setSelected, setLastGraph }) {
  const fileRef = useRef(null);            // hidden handle on the file input (kept for future use)
  const [msg, setMsg] = useState("");          // upload / list error shown in the upload bar
  const [question, setQuestion] = useState(""); // current text in the prompt box
  const [result, setResult] = useState(null);   // last answer returned by the backend
  const [busy, setBusy] = useState(false);      // true while a question is being answered
  const [qError, setQError] = useState("");     // error from the last question, if any

  // Re-fetch the document list from the backend and store it in App's state.
  // Any failure is shown in the upload bar instead of crashing the page.
  const refresh = () => api.documents().then(setDocs).catch((e) => setMsg(e.message));

  // Load the list once when the tab first opens.
  useEffect(() => { refresh(); }, []);

  // While any document is still 'processing', poll every 3 seconds so its state flips to
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

  // Tick or untick one document for querying: remove the id if it is already selected,
  // otherwise add it. (Only 'ready' documents have an enabled checkbox.)
  const toggle = (id) => setSelected(selected.includes(id) ? selected.filter((x) => x !== id) : [...selected, id]);

  // Send the question and the selected document ids to the backend (GraphRAG mode).
  // Clears the previous answer first so stale results never sit next to a new question, then
  // stores the new answer and passes its graph up so the Graph Explorer can highlight the path.
  async function ask() {
    setBusy(true); setQError(""); setResult(null);
    try {
      const r = await api.query(question, selected, "graph");
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

  // The Ask button and the Enter shortcut share this one rule: not already working, a
  // question of at least 3 characters, and at least one document selected.
  const canAsk = !busy && question.trim().length >= 3 && selected.length > 0;

  // Small helper line under the prompt. When Ask is disabled because nothing is selected we
  // say why, instead of leaving the user with a silently greyed-out button.
  const hint = selected.length === 0
    ? "Tick at least one ready document above to ask a question."
    : `${selected.length} document(s) selected`;

  // The answer pane is shown while waiting, on success, and on error.
  const showAnswerPane = busy || result || qError;

  return (
    <div className="workspace">
      {/* 1. Upload bar: fixed height at the top */}
      <section className="card upload-bar">
        <h2>Documents</h2>
        <input ref={fileRef} type="file" accept="application/pdf" onChange={upload} />
        {msg && <div className="err">{msg}</div>}
      </section>

      {/* 2. Documents pane: takes the leftover height and scrolls on its own */}
      <section className="card pane docs-pane">
        <div className="scroll">
          <table>
            <thead><tr><th></th><th>Name</th><th>State</th><th></th></tr></thead>
            <tbody>
              {docs.map((d) => (
                <tr key={d.id}>
                  <td><input type="checkbox" disabled={d.status !== "ready"} checked={selected.includes(d.id)} onChange={() => toggle(d.id)} /></td>
                  <td>{d.name} {d.is_global && <span className="muted">(global corpus)</span>}</td>
                  <td>
                    <span className={`badge ${d.status}`}>{d.status}</span>
                    {d.status === "processing" && <div className="muted">{d.stage}</div>}
                    {d.status === "failed" && <div className="err">{d.error}</div>}
                  </td>
                  <td>
                    {d.status === "failed" && !d.is_global && <button className="link" onClick={() => api.retry(d.id).then(refresh)}>Retry</button>}
                    {!d.is_global && <button className="link" onClick={() => window.confirm("Delete this document and its index?") && api.remove(d.id).then(refresh)}>Delete</button>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
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
        <div className="prompt-row">
          <textarea
            rows={2}
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={onPromptKeyDown}
            placeholder="Ask about the selected documents (Enter to send, Shift+Enter for a new line)"
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
