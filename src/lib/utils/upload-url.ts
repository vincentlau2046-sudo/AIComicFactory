/**
 * Convert a local file path (e.g., "./uploads/frames/abc.png") to an API URL
 * for serving via /api/uploads/[...path].
 */
export function uploadUrl(filePath: string): string {
  // Normalize backslashes to forward slashes (Windows compatibility)
  const normalized = filePath.replace(/\\/g, "/");

  // Already an API URL — return as-is
  if (normalized.startsWith("/api/uploads/")) return normalized;

  // Strip any prefix ending with "uploads/" (handles ./uploads/, /abs/path/uploads/, etc.)
  const stripped = normalized.replace(/^.*?uploads\//, "");

  return `/api/uploads/${stripped}`;
}
