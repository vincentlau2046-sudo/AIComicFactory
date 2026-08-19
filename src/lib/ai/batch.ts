/**
 * Bounded-concurrency batch processing.
 * Processes items in chunks of `limit` in parallel,
 * waiting for each chunk before starting the next.
 */
export async function parallelLimit<T>(
  items: T[],
  limit: number,
  fn: (item: T, index: number) => Promise<void>
): Promise<void> {
  for (let i = 0; i < items.length; i += limit) {
    const batch = items.slice(i, i + limit);
    await Promise.all(
      batch.map((item, j) => fn(item, i + j))
    );
  }
}