/** Versioned JSON payloads, byte-identical to satchel_core.payloads.to_http. */

const VERSION = 1;
const B36 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ";
const B32 = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
const HEADER_LEN = 8;
const MAX_PART_CHARS = 1000;

function sortedStringify(value: unknown): string {
  if (Array.isArray(value)) {
    return `[${value.map(sortedStringify).join(",")}]`;
  }
  if (value !== null && typeof value === "object") {
    const obj = value as Record<string, unknown>;
    const entries = Object.keys(obj)
      .sort()
      .map((key) => `${jsonString(key)}:${sortedStringify(obj[key])}`);
    return `{${entries.join(",")}}`;
  }
  return jsonString(value);
}

function jsonString(value: unknown): string {
  return JSON.stringify(value).replace(/[^\x00-\x7F]/g, (c) => {
    const code = c.codePointAt(0)!;
    if (code <= 0xffff) {
      return `\\u${code.toString(16).padStart(4, "0")}`;
    }
    const n = code - 0x10000;
    const hi = 0xd800 + (n >> 10);
    const lo = 0xdc00 + (n & 0x3ff);
    return `\\u${hi.toString(16)}\\u${lo.toString(16)}`;
  });
}

function encodePayload(body: Record<string, unknown>, type: string): string {
  return sortedStringify({ v: VERSION, t: type, b: body });
}

function base32Encode(data: Uint8Array): string {
  let bits = 0;
  let value = 0;
  let out = "";
  for (const byte of data) {
    value = (value << 8) | byte;
    bits += 8;
    while (bits >= 5) {
      out += B32[(value >>> (bits - 5)) & 31];
      bits -= 5;
    }
  }
  if (bits > 0) {
    out += B32[(value << (5 - bits)) & 31];
  }
  return out;
}

function b36(value: number): string {
  return B36[Math.floor(value / 36)]! + B36[value % 36]!;
}

export function bbqrSplit(
  text: string,
  fileType = "J",
  maxPartChars = MAX_PART_CHARS,
): string[] {
  const encoded = base32Encode(new TextEncoder().encode(text));
  const maxData = Math.floor((maxPartChars - HEADER_LEN) / 8) * 8;
  const total = Math.max(1, Math.ceil(encoded.length / maxData));
  const per = Math.ceil(Math.ceil(encoded.length / total) / 8) * 8;
  const parts: string[] = [];
  for (let index = 0; index < total; index++) {
    const chunk = encoded.slice(index * per, (index + 1) * per);
    parts.push(`B$2${fileType}${b36(total)}${b36(index)}${chunk}`);
  }
  return parts;
}

export function toHttp(
  type: string,
  body: Record<string, unknown>,
): { type: string; payload: string; parts: string[] } {
  const payload = encodePayload(body, type);
  return { type, payload, parts: bbqrSplit(payload) };
}
