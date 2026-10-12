export function partAt(parts: string[], index: number): string | null {
  if (parts.length === 0) return null;
  const safe = ((index % parts.length) + parts.length) % parts.length;
  return parts[safe];
}

export function nextIndex(parts: string[], index: number): number {
  if (parts.length <= 1) return 0;
  return (index + 1) % parts.length;
}
