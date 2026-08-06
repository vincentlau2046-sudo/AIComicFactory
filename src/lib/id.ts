import { customAlphabet } from "nanoid";

const alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz";
const generate = customAlphabet(alphabet, 12);

/**
 * Generate a short, URL-safe unique ID (12 chars, 62^12 ≈ 3.2×10^21 space).
 * Drop-in replacement for ulid() — same usage: `id()`.
 */
export function id(): string {
  return generate();
}
