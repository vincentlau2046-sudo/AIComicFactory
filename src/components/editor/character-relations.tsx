"use client";

import { useState, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { apiFetch } from "@/lib/api-fetch";
import { Plus, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";

const RELATION_TYPES = [
  "ally", "enemy", "lover", "family", "mentor", "rival", "stranger", "neutral",
];

interface Character {
  id: string;
  name: string;
}

interface Relation {
  id: string;
  characterAId: string;
  characterBId: string;
  relationType: string;
  description: string;
}

export function CharacterRelations({
  projectId,
  characters,
}: {
  projectId: string;
  characters: Character[];
}) {
  const tChar = useTranslations("character");
  const [relations, setRelations] = useState<Relation[]>([]);
  const [charA, setCharA] = useState("");
  const [charB, setCharB] = useState("");
  const [relType, setRelType] = useState("neutral");
  const [desc, setDesc] = useState("");

  const [allCharacters, setAllCharacters] = useState<Character[]>([]);

  useEffect(() => {
    // Load all project characters for name resolution
    apiFetch(`/api/projects/${projectId}/characters`)
      .then((r) => r.json())
      .then((data) => setAllCharacters(Array.isArray(data) ? data : data.characters || []))
      .catch(() => {});

    apiFetch(`/api/projects/${projectId}/character-relations`)
      .then((r) => r.json())
      .then(setRelations)
      .catch(() => {});
  }, [projectId]);

  async function handleAdd() {
    if (!charA || !charB || charA === charB) return;
    const resp = await apiFetch(`/api/projects/${projectId}/character-relations`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        characterAId: charA,
        characterBId: charB,
        relationType: relType,
        description: desc,
      }),
    });
    const newRel = await resp.json();
    setRelations((prev) => [...prev, newRel]);
    setDesc("");
  }

  async function handleDelete(id: string) {
    await apiFetch(`/api/projects/${projectId}/character-relations/${id}`, {
      method: "DELETE",
    });
    setRelations((prev) => prev.filter((r) => r.id !== id));
  }

  const getName = (id: string) =>
    characters.find((c) => c.id === id)?.name ||
    allCharacters.find((c) => c.id === id)?.name ||
    "?";

  // Filter: only show relations where BOTH characters are in current character list
  const charIds = new Set(characters.map((c) => c.id));
  const filteredRelations = relations.filter(
    (r) => charIds.has(r.characterAId) && charIds.has(r.characterBId)
  );

  if (characters.length < 2) return null;

  return (
    <div className="space-y-3 rounded-lg border p-4">
      <h3 className="text-sm font-medium">{tChar("relations")}</h3>

      {filteredRelations.map((rel) => (
        <div key={rel.id} className="flex items-center gap-2 rounded border p-2 text-sm">
          <span className="font-medium">{getName(rel.characterAId)}</span>
          <span className="rounded bg-muted px-2 py-0.5 text-xs">{tChar(`relType_${rel.relationType}`)}</span>
          <span className="font-medium">{getName(rel.characterBId)}</span>
          {rel.description && (
            <span className="text-muted-foreground truncate">&mdash; {rel.description}</span>
          )}
          <Button variant="ghost" size="sm" onClick={() => handleDelete(rel.id)} className="ml-auto shrink-0">
            <Trash2 className="h-3 w-3" />
          </Button>
        </div>
      ))}

      <div className="flex flex-wrap items-end gap-2">
        <select
          value={charA}
          onChange={(e) => setCharA(e.target.value)}
          className="h-9 rounded-md border bg-background px-3 text-sm"
        >
          <option value="">{tChar("characterA")}</option>
          {characters.map((c) => (
            <option key={c.id} value={c.id}>{c.name}</option>
          ))}
        </select>
        <select
          value={relType}
          onChange={(e) => setRelType(e.target.value)}
          className="h-9 rounded-md border bg-background px-3 text-sm"
        >
          {RELATION_TYPES.map((rt) => (
            <option key={rt} value={rt}>{tChar(`relType_${rt}`)}</option>
          ))}
        </select>
        <select
          value={charB}
          onChange={(e) => setCharB(e.target.value)}
          className="h-9 rounded-md border bg-background px-3 text-sm"
        >
          <option value="">{tChar("characterB")}</option>
          {characters.map((c) => (
            <option key={c.id} value={c.id}>{c.name}</option>
          ))}
        </select>
        <Input
          value={desc}
          onChange={(e) => setDesc(e.target.value)}
          placeholder={tChar("relationDesc")}
          className="w-48"
        />
        <Button size="sm" onClick={handleAdd} disabled={!charA || !charB || charA === charB}>
          <Plus className="mr-1 h-3 w-3" />
          {tChar("addRelation")}
        </Button>
      </div>
    </div>
  );
}
