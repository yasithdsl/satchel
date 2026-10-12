const BECH32_RE = /\bbc(?:rt)?1[a-z0-9]{8,}\b/g;
const HEX64_RE = /\b[0-9a-fA-F]{64}\b/g;

export function maskSecrets(text: string): string {
  return text
    .replace(BECH32_RE, "·address hidden·")
    .replace(HEX64_RE, "·id hidden·");
}
