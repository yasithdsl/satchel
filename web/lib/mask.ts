const BECH32_RE = /\bbc(?:rt)?1[a-z0-9]{8,}\b/g;
const HEX_ID_RE = /\b(?:0x)?[0-9a-fA-F]{32,64}\b/g;

export function maskSecrets(text: string): string {
  return text
    .replace(BECH32_RE, "·address hidden·")
    .replace(HEX_ID_RE, "·id hidden·");
}
