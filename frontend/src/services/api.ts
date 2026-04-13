const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000/api";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    throw new Error(`API error: ${res.status} ${res.statusText}`);
  }
  return res.json();
}

export const api = {
  health: () => request<{ status: string }>("/health"),

  // Projects
  listProjects: () => request("/projects"),
  createProject: (data: Record<string, unknown>) =>
    request("/projects", { method: "POST", body: JSON.stringify(data) }),

  // Documents
  uploadDocument: (file: File, projectId: number) => {
    const formData = new FormData();
    formData.append("file", file);
    return fetch(`${API_BASE}/documents/upload?project_id=${projectId}`, {
      method: "POST",
      body: formData,
    }).then((res) => res.json());
  },

  // Analysis
  startAnalysis: (projectId: number) =>
    request(`/analysis/start/${projectId}`, { method: "POST" }),
  getAnalysisResult: (projectId: number) =>
    request(`/analysis/result/${projectId}`),
};
