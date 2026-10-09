import { supabase } from "./supabase";

// Empty locally (Vite proxy or nginx forwards /api). Set to the Render URL for the Netlify build.
const API_URL = import.meta.env.VITE_API_URL || "";

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

export const api = {
  me: () => request("/api/me"),
  setUsername: (username) => request("/api/me/username", { method: "PUT", json: { username } }),
  documents: () => request("/api/documents"),
  upload: (file, override = false) => {
    const form = new FormData();
    form.append("file", file);
    return request(`/api/documents?override=${override}`, { method: "POST", body: form });
  },
  retry: (id) => request(`/api/documents/${id}/retry`, { method: "POST" }),
  remove: (id) => request(`/api/documents/${id}`, { method: "DELETE" }),
  sourceUrl: (id) => request(`/api/documents/${id}/url`),
  query: (question, doc_ids, mode = "graph") =>
    request("/api/query", { method: "POST", json: { question, doc_ids, mode } }),
  benchmark: (question, doc_ids) =>
    request("/api/benchmark", { method: "POST", json: { question, doc_ids } }),
  graph: (docIds, search = "", types = []) =>
    request(`/api/graph?doc_ids=${docIds.join(",")}&search=${encodeURIComponent(search)}&types=${types.join(",")}`),
  graphTypes: () => request("/api/graph/types"),
  expand: (id, docIds) => request(`/api/graph/expand/${id}?doc_ids=${docIds.join(",")}`),
  node: (id, docIds) => request(`/api/graph/node/${id}?doc_ids=${docIds.join(",")}`),
};
