import { supabase } from "./supabase";

// Empty locally (Vite proxy or nginx forwards /api). Set to the Render URL for the Netlify build.
const API_URL = import.meta.env.VITE_API_URL || "";

// Shared fetch wrapper used by every call below. It attaches the Supabase access token, sends JSON when
// options.json is given, and turns error responses into an Error carrying .status and .detail
// (Workspace uses status 409 to detect duplicate uploads). A 204 response returns null.
async function request(path, options = {}) {
  const { data } = await supabase.auth.getSession();
  const token = data.session?.access_token;
  const headers = { ...(options.headers || {}), Authorization: `Bearer ${token}` };
  if (options.json) {
    headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(options.json);
  }
  const res = await fetch(`${API_URL}${path}`, { ...options, headers });
  if (res.status === 204) return null;
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = body.detail;
    const err = new Error(typeof detail === "string" ? detail : detail?.message || "Request failed");
    err.status = res.status;
    err.detail = detail;
    throw err;
  }
  return body;
}

// One function per backend endpoint, so components never build URLs themselves.
export const api = {
  // Current user's profile
  me: () => request("/api/me"),
  setUsername: (username) => request("/api/me/username", { method: "PUT", json: { username } }),
  // Library: the list endpoint is paged; follow next_cursor until the server says there is no more
  documents: async () => {
    const items = [];
    let cursor = null;
    do {
      const page = await request(`/api/documents?limit=100${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`);
      items.push(...page.items);
      cursor = page.next_cursor;
    } while (cursor);
    return items;
  },
  // The backend reads override as a form field, so it goes into the multipart body
  upload: (file, override = false) => {
    const form = new FormData();
    form.append("file", file);
    form.append("override", String(override));
    return request("/api/documents", { method: "POST", body: form });
  },
  retry: (id) => request(`/api/documents/${id}/retry`, { method: "POST" }),
  remove: (id) => request(`/api/documents/${id}`, { method: "DELETE" }),
  sourceUrl: (id) => request(`/api/documents/${id}/download`),
  // Groups: named sets of library papers. Membership calls return the updated group record.
  groups: () => request("/api/groups"),
  createGroup: (name) => request("/api/groups", { method: "POST", json: { name } }),
  renameGroup: (id, name) => request(`/api/groups/${id}`, { method: "PATCH", json: { name } }),
  deleteGroup: (id) => request(`/api/groups/${id}`, { method: "DELETE" }),
  addToGroup: (id, docId) => request(`/api/groups/${id}/documents/${docId}`, { method: "PUT" }),
  removeFromGroup: (id, docId) => request(`/api/groups/${id}/documents/${docId}`, { method: "DELETE" }),
  // Paper graph of a group's ready papers, optionally filtered by paper name
  groupGraph: (id, search = "") =>
    request(`/api/groups/${id}/graph?search=${encodeURIComponent(search)}&limit=50&per_paper=5`),
  // Ask a question over the papers of one group
  query: (question, group_id) => request("/api/query", { method: "POST", json: { question, group_id } }),
  // Run the same question through Standard RAG and GraphRAG over one group for the Benchmarks tab
  benchmark: (question, group_id) => request("/api/benchmark", { method: "POST", json: { question, group_id } }),
};
