/**
 * Runtime-safe environment variable accessors.
 * Throws on missing required vars instead of silently falling back to relative paths.
 */
export function getUploadDir(): string {
  const dir = process.env.UPLOAD_DIR;
  if (!dir) throw new Error("UPLOAD_DIR environment variable is not set. Add UPLOAD_DIR=/absolute/path to .env");
  return dir;
}