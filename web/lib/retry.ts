const DEFAULT_BUDGET_MS = 45_000;
const DEFAULT_INTERVAL_MS = 1_500;

export function isBusyError(err: unknown): boolean {
  return err instanceof Error && err.message.includes("409");
}

export async function retryWhileBusy<T>(
  fn: () => Promise<T>,
  opts: {
    budgetMs?: number;
    intervalMs?: number;
    sleep?: (ms: number) => Promise<void>;
  } = {},
): Promise<T> {
  const budget = opts.budgetMs ?? DEFAULT_BUDGET_MS;
  const interval = opts.intervalMs ?? DEFAULT_INTERVAL_MS;
  const sleep = opts.sleep ?? ((ms: number) => new Promise<void>((r) => setTimeout(r, ms)));
  const deadline = Date.now() + budget;
  while (true) {
    try {
      return await fn();
    } catch (err) {
      if (!isBusyError(err) || Date.now() >= deadline) throw err;
      await sleep(interval);
    }
  }
}
