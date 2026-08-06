"use client";

import { useState, useMemo } from "react";
import { useTranslations } from "next-intl";

interface Shot {
  id: string;
  sequence: number;
  firstFrame?: string | null;
  lastFrame?: string | null;
  prompt?: string;
  duration: number;
}

interface Version {
  id: string;
  label: string;
  versionNum: number;
}

interface VersionCompareProps {
  versions: Version[];
  currentVersionId: string | null;
  onVersionChange: (versionId: string) => void;
  getShotsForVersion: (versionId: string) => Shot[];
}

export function VersionCompare({
  versions,
  currentVersionId,
  onVersionChange,
  getShotsForVersion,
}: VersionCompareProps) {
  const t = useTranslations();
  const [versionAId, setVersionAId] = useState(versions[0]?.id || "");
  const [versionBId, setVersionBId] = useState(versions[1]?.id || "");

  const shotsA = useMemo(() => getShotsForVersion(versionAId), [versionAId, getShotsForVersion]);
  const shotsB = useMemo(() => getShotsForVersion(versionBId), [versionBId, getShotsForVersion]);

  const maxLen = Math.max(shotsA.length, shotsB.length);

  if (versions.length < 2) {
    return (
      <div className="rounded-lg border p-4 text-center text-sm text-muted-foreground">
        {t("storyboard.needTwoVersions")}
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Version selectors */}
      <div className="flex items-center gap-4">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium">A:</span>
          <select
            value={versionAId}
            onChange={(e) => setVersionAId(e.target.value)}
            className="h-8 rounded-md border bg-background px-2 text-sm"
          >
            {versions.map((v) => (
              <option key={v.id} value={v.id}>
                v{v.versionNum} — {v.label}
              </option>
            ))}
          </select>
        </div>
        <span className="text-muted-foreground">vs</span>
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium">B:</span>
          <select
            value={versionBId}
            onChange={(e) => setVersionBId(e.target.value)}
            className="h-8 rounded-md border bg-background px-2 text-sm"
          >
            {versions.map((v) => (
              <option key={v.id} value={v.id}>
                v{v.versionNum} — {v.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* Side-by-side comparison */}
      <div className="space-y-4">
        {Array.from({ length: maxLen }, (_, i) => {
          const shotA = shotsA[i];
          const shotB = shotsB[i];
          return (
            <div key={i} className="grid grid-cols-2 gap-4 rounded-lg border p-3">
              <div className="space-y-1">
                <span className="text-xs font-medium text-muted-foreground">
                  {t("shot.shot")} {i + 1} — v{versions.find((v) => v.id === versionAId)?.versionNum}
                </span>
                {shotA?.firstFrame ? (
                  <img
                    src={shotA.firstFrame}
                    alt={`Shot ${i + 1} version A`}
                    className="w-full rounded aspect-video object-cover"
                  />
                ) : (
                  <div className="w-full rounded aspect-video bg-muted flex items-center justify-center text-xs text-muted-foreground">
                    {t("storyboard.noFrame")}
                  </div>
                )}
                {shotA?.prompt && (
                  <p className="text-xs text-muted-foreground line-clamp-2">{shotA.prompt}</p>
                )}
              </div>
              <div className="space-y-1">
                <span className="text-xs font-medium text-muted-foreground">
                  {t("shot.shot")} {i + 1} — v{versions.find((v) => v.id === versionBId)?.versionNum}
                </span>
                {shotB?.firstFrame ? (
                  <img
                    src={shotB.firstFrame}
                    alt={`Shot ${i + 1} version B`}
                    className="w-full rounded aspect-video object-cover"
                  />
                ) : (
                  <div className="w-full rounded aspect-video bg-muted flex items-center justify-center text-xs text-muted-foreground">
                    {t("storyboard.noFrame")}
                  </div>
                )}
                {shotB?.prompt && (
                  <p className="text-xs text-muted-foreground line-clamp-2">{shotB.prompt}</p>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
