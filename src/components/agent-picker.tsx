"use client";

import { useEffect, useState, useRef } from "react";
import { useAgentStore } from "@/stores/agent-store";
import { useTranslations } from "next-intl";
import { Bot, ChevronDown, Check } from "lucide-react";

interface AgentPickerProps {
  projectId: string;
  category: string;
}

export function AgentPicker({ projectId, category }: AgentPickerProps) {
  const t = useTranslations("settings");
  const { agents, bindings, fetchAgents, fetchBindings, setBinding } = useAgentStore();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    fetchAgents();
    fetchBindings(projectId);
  }, [projectId, fetchAgents, fetchBindings]);

  // Close on outside click
  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    if (open) document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [open]);

  const availableAgents = agents.filter((a) => a.category === category);
  const currentBinding = bindings.find((b) => b.category === category);
  const selectedAgent = availableAgents.find((a) => a.id === currentBinding?.agentId);

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen(!open)}
        className={`flex h-7 items-center gap-1.5 rounded-lg border px-2 text-[11px] font-medium transition-all duration-150 ${
          selectedAgent
            ? "border-primary/30 bg-primary/5 text-primary hover:bg-primary/10"
            : "border-[--border-subtle] bg-white text-[--text-muted] hover:border-[--border-hover] hover:text-[--text-secondary]"
        }`}
      >
        <Bot className="h-3 w-3" />
        <span className="max-w-[80px] truncate">
          {selectedAgent ? selectedAgent.name : t("defaultAgent")}
        </span>
        <ChevronDown className={`h-2.5 w-2.5 transition-transform ${open ? "rotate-180" : ""}`} />
      </button>

      {open && (
        <div className="absolute right-0 top-full z-50 mt-1 min-w-[180px] rounded-xl border border-[--border-subtle] bg-white p-1 shadow-lg shadow-black/8 animate-in fade-in slide-in-from-top-1 duration-150">
          {/* Default option */}
          <button
            onClick={() => { setBinding(projectId, category, null); setOpen(false); }}
            className={`flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-xs transition-colors ${
              !selectedAgent
                ? "bg-[--surface] text-[--text-primary] font-medium"
                : "text-[--text-secondary] hover:bg-[--surface]"
            }`}
          >
            <div className="flex h-5 w-5 items-center justify-center rounded-md bg-[--surface] text-[--text-muted]">
              <Bot className="h-3 w-3" />
            </div>
            <span className="flex-1">{t("defaultAgent")}</span>
            {!selectedAgent && <Check className="h-3 w-3 text-primary" />}
          </button>

          {availableAgents.length > 0 && (
            <div className="my-1 h-px bg-[--border-subtle]" />
          )}

          {availableAgents.map((agent) => {
            const isSelected = selectedAgent?.id === agent.id;
            return (
              <button
                key={agent.id}
                onClick={() => { setBinding(projectId, category, agent.id); setOpen(false); }}
                className={`flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-xs transition-colors ${
                  isSelected
                    ? "bg-primary/5 text-primary font-medium"
                    : "text-[--text-secondary] hover:bg-[--surface]"
                }`}
              >
                <div className={`flex h-5 w-5 items-center justify-center rounded-md text-[10px] font-bold ${
                  isSelected ? "bg-primary/10 text-primary" : "bg-[--surface] text-[--text-muted]"
                }`}>
                  {agent.name[0]?.toUpperCase()}
                </div>
                <span className="flex-1 truncate">{agent.name}</span>
                {isSelected && <Check className="h-3 w-3 text-primary" />}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
