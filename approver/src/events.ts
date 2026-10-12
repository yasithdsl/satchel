/** Shared JSONL event stream, same record shape as satchel_core.events.emit. */

import { appendFileSync, mkdirSync } from "node:fs";
import { randomUUID } from "node:crypto";
import { dirname } from "node:path";
import { fileURLToPath } from "node:url";

const DEFAULT_LOG = fileURLToPath(
  new URL("../../.satchel/events.jsonl", import.meta.url),
);

export function emit(
  component: string,
  type: string,
  message: string,
  payload: Record<string, unknown> | null = null,
): Record<string, unknown> {
  if (!component) throw new Error("component must not be empty");
  if (!type) throw new Error("type must not be empty");
  if (!message) throw new Error("message must not be empty");
  const ts = new Date().toISOString().replace("Z", "+00:00");
  const record = {
    id: randomUUID().replaceAll("-", ""),
    ts,
    component,
    type,
    message,
    payload,
  };
  const path = process.env.SATCHEL_EVENT_LOG || DEFAULT_LOG;
  const line = JSON.stringify(record);
  mkdirSync(dirname(path), { recursive: true });
  appendFileSync(path, line + "\n");
  process.stderr.write(`${ts} [${component}] ${type}: ${message}\n`);
  return record;
}
