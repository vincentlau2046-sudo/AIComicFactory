import { create } from "zustand";
import { apiFetch } from "@/lib/api-fetch";

interface AgentBinding {
  category: string;
  agentId: string | null;
  agentName: string | null;
}

interface AgentInfo {
  id: string;
  name: string;
  category: string;
}

interface AgentStore {
  agents: AgentInfo[];
  bindings: AgentBinding[];
  loading: boolean;
  fetchAgents: () => Promise<void>;
  fetchBindings: (projectId: string) => Promise<void>;
  setBinding: (projectId: string, category: string, agentId: string | null) => Promise<void>;
}

export const useAgentStore = create<AgentStore>((set, get) => ({
  agents: [],
  bindings: [],
  loading: false,

  fetchAgents: async () => {
    const res = await apiFetch("/api/agents");
    if (res.ok) {
      set({ agents: await res.json() });
    }
  },

  fetchBindings: async (projectId: string) => {
    set({ loading: true });
    const res = await apiFetch(`/api/projects/${projectId}/agent-bindings`);
    if (res.ok) {
      set({ bindings: await res.json(), loading: false });
    } else {
      set({ loading: false });
    }
  },

  setBinding: async (projectId: string, category: string, agentId: string | null) => {
    await apiFetch(`/api/projects/${projectId}/agent-bindings`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ category, agentId }),
    });
    get().fetchBindings(projectId);
  },
}));
