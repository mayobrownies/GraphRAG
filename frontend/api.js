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
  // Documents: the list endpoint is paged (default 50); this returns only the first page's items
  documents: () => request("/api/documents").then((page) => page.items),
  upload: (file, override = false) => {
    const form = new FormData();
    form.append("file", file);
    return request(`/api/documents?override=${override}`, { method: "POST", body: form });
  },
  retry: (id) => request(`/api/documents/${id}/retry`, { method: "POST" }),
  remove: (id) => request(`/api/documents/${id}`, { method: "DELETE" }),
  sourceUrl: (id) => request(`/api/documents/${id}/download`),
  // Ask a question over the given documents; mode is "graph" (GraphRAG) or standard RAG
  query: (question, doc_ids, mode = "graph") =>
    request("/api/query", { method: "POST", json: { question, doc_ids, mode } }),
  // Run the same question through Standard RAG and GraphRAG for the Benchmarks tab
  benchmark: (question, doc_ids) =>
    request("/api/benchmark", { method: "POST", json: { question, doc_ids } }),
  // Graph Explorer: search/filter the graph, list node types, expand a node, or inspect one node
  graph: (docIds, search = "", types = []) =>
    request(`/api/graph?doc_ids=${docIds.join(",")}&search=${encodeURIComponent(search)}&types=${types.join(",")}`),
  graphTypes: () => request("/api/graph/types"),
  expand: (id, docIds) => request(`/api/graph/expand/${id}?doc_ids=${docIds.join(",")}`),
  node: (id, docIds) => request(`/api/graph/node/${id}?doc_ids=${docIds.join(",")}`),
};
