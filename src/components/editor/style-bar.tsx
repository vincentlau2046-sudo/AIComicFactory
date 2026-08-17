"use client";

import { useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { useProjectStore } from "@/stores/project-store";
import { apiFetch } from "@/lib/api-fetch";
import { cn } from "@/lib/utils";
import { VISUAL_STYLE_ENTRIES, ERA_CATEGORIES } from "@/lib/ai/prompts/style-registry";
import { Film, Globe, Palette, ChevronDown, Check, Pencil } from "lucide-react";

// --- Style dropdown ---

function StyleDropdown({
  value,
  options,
  placeholder,
  icon: Icon,
  label,
  onSelect,
  allowCustom = true,
}: {
  value: string;
  options: Array<{ label: string; description: string; key: string }>;
  placeholder: string;
  icon: React.ElementType;
  label: string;
  onSelect: (label: string, key: string) => void;
  allowCustom?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [custom, setCustom] = useState(false);
  const [customText, setCustomText] = useState("");
  const selected = options.find((o) => o.label === value);

  return (
    <div className="relative">
      <button
        onClick={() => setOpen(!open)}
        className={cn(
          "flex w-full items-center gap-2 rounded-xl border px-3 py-2 text-left text-sm transition-all",
          value
            ? "border-[--border-subtle] bg-white hover:border-primary/30"
            : "border-dashed border-[--border-subtle] bg-[--surface] text-[--text-muted]"
        )}
      >
        <Icon className="h-4 w-4 flex-shrink-0 text-[--text-muted]" />
        <span className={cn("flex-1 truncate", !value && "italic")}>
          {value || placeholder}
        </span>
        <ChevronDown className={cn("h-3.5 w-3.5 text-[--text-muted] transition-transform", open && "rotate-180")} />
      </button>

      {open && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
          <div className="absolute left-0 right-0 top-full z-20 mt-1 max-h-60 overflow-auto rounded-xl border border-[--border-subtle] bg-white shadow-lg">
            {/* Clear option */}
            <button
              onClick={() => { onSelect("", ""); setOpen(false); }}
              className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-[--text-muted] hover:bg-[--surface]"
            >
              <span className="flex-1 italic">
                {label === "style" ? "无 / 清空" : label === "era" ? "无 / 清空" : "无 / 清空"}
              </span>
              {!value && <Check className="h-3.5 w-3.5 text-primary" />}
            </button>

            {/* Preset options */}
            {options.map((o) => (
              <button
                key={o.key}
                onClick={() => { onSelect(o.label, o.key); setOpen(false); }}
                className="flex w-full items-start gap-2 px-3 py-2 text-left hover:bg-[--surface]"
              >
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-1.5">
                    <span className="text-sm font-medium text-[--text-primary]">{o.label}</span>
                    {o.label === value && <Check className="h-3.5 w-3.5 flex-shrink-0 text-primary" />}
                  </div>
                  <p className="mt-0.5 text-[10px] leading-relaxed text-[--text-muted] line-clamp-2">
                    {o.description}
                  </p>
                </div>
              </button>
            ))}

            {/* Custom entry */}
            {allowCustom && (
              <div className="border-t border-[--border-subtle] p-2">
                {custom ? (
                  <div className="flex gap-1">
                    <input
                      autoFocus
                      value={customText}
                      onChange={(e) => setCustomText(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" && customText.trim()) {
                          onSelect(customText.trim(), "__custom__");
                          setOpen(false); setCustom(false); setCustomText("");
                        }
                      }}
                      placeholder="输入自定义..."
                      className="flex-1 rounded-lg border border-[--border-subtle] px-2 py-1 text-xs outline-none focus:border-primary/50"
                    />
                  </div>
                ) : (
                  <button
                    onClick={() => setCustom(true)}
                    className="flex w-full items-center gap-1.5 rounded-lg px-2 py-1.5 text-xs text-[--text-muted] hover:bg-[--surface]"
                  >
                    <Pencil className="h-3 w-3" />
                    自定义...
                  </button>
                )}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}

// --- Main component ---

interface StyleBarProps {
  projectId: string;
  episodeId?: string;
  visualStyle?: string;
  visualStyleKey?: string;
  eraAesthetic?: string;
  moodDirection?: string;
}

const MOOD_TEMPLATES = [
  { key: "dark-to-light", label: "压抑→希望", labelEn: "Dark → Hopeful" },
  { key: "calm-to-intense", label: "平静→激烈", labelEn: "Calm → Intense" },
  { key: "warm-intimate", label: "温暖亲密", labelEn: "Warm & Intimate" },
  { key: "cold-solemn", label: "冷峻肃穆", labelEn: "Cold & Solemn" },
  { key: "heroic-epic", label: "英雄史诗", labelEn: "Heroic & Epic" },
  { key: "tense-suspense", label: "紧张悬疑", labelEn: "Tense & Suspenseful" },
];

export function StyleBar({ projectId, episodeId, visualStyle, visualStyleKey, eraAesthetic, moodDirection }: StyleBarProps) {
  const t = useTranslations("project");
  const locale = useLocale();
  const { fetchProject } = useProjectStore();

  const updateStyle = async (field: string, label: string, key: string) => {
    const body: Record<string, string> = { [field]: label };
    if (field === "visualStyle") (body as any).visualStyleKey = key;
    await apiFetch(`/api/projects/${projectId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    fetchProject(projectId, episodeId);
  };

  const visualOptions = VISUAL_STYLE_ENTRIES.map((s) => ({
    key: s.key,
    label: locale === "zh" ? s.label : s.label,
    description: s.description,
  }));

  const eraOptions = ERA_CATEGORIES.map((e) => ({
    key: e.key,
    label: locale === "zh" ? e.label : e.label,
    description: e.description,
  }));

  const moodOptions = MOOD_TEMPLATES.map((m) => ({
    key: m.key,
    label: locale === "zh" ? m.label : m.labelEn,
    description: "",
  }));

  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
      {/* Visual Style */}
      <div className="rounded-2xl border border-[--border-subtle] bg-white p-3">
        <p className="mb-2 text-[10px] font-semibold uppercase tracking-[0.15em] text-[--text-muted">
          🎬 { t("styleVisual") }
        </p>
        <StyleDropdown
          value={visualStyle || ""}
          options={visualOptions}
          placeholder={ t("styleVisualPlaceholder") }
          icon={Film}
          label="style"
          onSelect={(label, key) => updateStyle("visualStyle", label, key)}
        />
      </div>

      {/* Era */}
      <div className="rounded-2xl border border-[--border-subtle] bg-white p-3">
        <p className="mb-2 text-[10px] font-semibold uppercase tracking-[0.15em] text-[--text-muted">
          🏛 { t("styleEra") }
        </p>
        <StyleDropdown
          value={eraAesthetic || ""}
          options={eraOptions}
          placeholder={ t("styleEraPlaceholder") }
          icon={Globe}
          label="era"
          onSelect={(label) => updateStyle("eraAesthetic", label, "")}
        />
      </div>

      {/* Mood */}
      <div className="rounded-2xl border border-[--border-subtle] bg-white p-3">
        <p className="mb-2 text-[10px] font-semibold uppercase tracking-[0.15em] text-[--text-muted">
          🎭 { t("styleMood") }
        </p>
        <StyleDropdown
          value={moodDirection || ""}
          options={moodOptions}
          placeholder={ t("styleMoodPlaceholder") }
          icon={Palette}
          label="mood"
          onSelect={(label) => updateStyle("moodDirection", label, "")}
        />
      </div>
    </div>
  );
}