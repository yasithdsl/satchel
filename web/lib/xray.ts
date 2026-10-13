export interface XrayEvent {
  seq: number;
  id: string;
  ts: string;
  component: string;
  type: string;
  message: string;
  payload: Record<string, unknown> | null;
  nodes?: { from?: string; to?: string; at?: string };
  label?: string;
  qr?: { type: string; parts: string[]; redacted: boolean };
  alert?: { level: string; title: string; reasons?: string[] };
  simulation?: boolean;
  boot?: string;
}

export function feedTime(ts: string): string {
  const parsed = new Date(ts);
  if (Number.isNaN(parsed.getTime())) return ts;
  return parsed.toLocaleTimeString("en-GB", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}
