"use client";

import { useMemo } from "react";

interface EmotionScore {
  shotSequence: number;
  tension: number; // 0-100
  emotion: number; // 0-100
}

interface EmotionCurveProps {
  scores: EmotionScore[];
}

export function EmotionCurve({ scores }: EmotionCurveProps) {
  const width = 600;
  const height = 100;
  const padding = { top: 10, right: 10, bottom: 20, left: 30 };

  const plotWidth = width - padding.left - padding.right;
  const plotHeight = height - padding.top - padding.bottom;

  const tensionPath = useMemo(() => {
    if (scores.length === 0) return "";
    return scores
      .map((s, i) => {
        const x = padding.left + (i / Math.max(1, scores.length - 1)) * plotWidth;
        const y = padding.top + plotHeight - (s.tension / 100) * plotHeight;
        return `${i === 0 ? "M" : "L"} ${x.toFixed(1)} ${y.toFixed(1)}`;
      })
      .join(" ");
  }, [scores, plotWidth, plotHeight]);

  const emotionPath = useMemo(() => {
    if (scores.length === 0) return "";
    return scores
      .map((s, i) => {
        const x = padding.left + (i / Math.max(1, scores.length - 1)) * plotWidth;
        const y = padding.top + plotHeight - (s.emotion / 100) * plotHeight;
        return `${i === 0 ? "M" : "L"} ${x.toFixed(1)} ${y.toFixed(1)}`;
      })
      .join(" ");
  }, [scores, plotWidth, plotHeight]);

  if (scores.length === 0) return null;

  return (
    <div className="rounded-lg border p-3">
      <div className="flex items-center gap-4 mb-2">
        <h4 className="text-xs font-medium">Rhythm Curve</h4>
        <div className="flex items-center gap-3 text-xs text-muted-foreground">
          <span className="flex items-center gap-1">
            <span className="inline-block w-3 h-0.5 bg-red-500" /> Tension
          </span>
          <span className="flex items-center gap-1">
            <span className="inline-block w-3 h-0.5 bg-blue-500" /> Emotion
          </span>
        </div>
      </div>
      <svg
        width={width}
        height={height}
        viewBox={`0 0 ${width} ${height}`}
        className="w-full"
        preserveAspectRatio="xMidYMid meet"
      >
        {/* Grid lines */}
        {[0, 25, 50, 75, 100].map((v) => {
          const y = padding.top + plotHeight - (v / 100) * plotHeight;
          return (
            <g key={v}>
              <line
                x1={padding.left}
                y1={y}
                x2={width - padding.right}
                y2={y}
                stroke="currentColor"
                strokeOpacity={0.1}
              />
              <text
                x={padding.left - 4}
                y={y + 3}
                textAnchor="end"
                fontSize={8}
                fill="currentColor"
                opacity={0.4}
              >
                {v}
              </text>
            </g>
          );
        })}

        {/* Shot markers on x-axis */}
        {scores.map((s, i) => {
          const x = padding.left + (i / Math.max(1, scores.length - 1)) * plotWidth;
          return (
            <text
              key={i}
              x={x}
              y={height - 4}
              textAnchor="middle"
              fontSize={8}
              fill="currentColor"
              opacity={0.4}
            >
              {s.shotSequence}
            </text>
          );
        })}

        {/* Tension line (red) */}
        <path d={tensionPath} fill="none" stroke="#ef4444" strokeWidth={2} />

        {/* Emotion line (blue) */}
        <path d={emotionPath} fill="none" stroke="#3b82f6" strokeWidth={1.5} strokeDasharray="4 2" />

        {/* Tension dots */}
        {scores.map((s, i) => {
          const x = padding.left + (i / Math.max(1, scores.length - 1)) * plotWidth;
          const y = padding.top + plotHeight - (s.tension / 100) * plotHeight;
          return <circle key={i} cx={x} cy={y} r={2.5} fill="#ef4444" />;
        })}
      </svg>
    </div>
  );
}
