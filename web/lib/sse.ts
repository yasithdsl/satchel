export interface SseMessage {
  id: string | null;
  data: string;
}

export class SseParser {
  private buffer = "";

  feed(chunk: string): SseMessage[] {
    this.buffer += chunk;
    const messages: SseMessage[] = [];
    let split = this.buffer.indexOf("\n\n");
    while (split !== -1) {
      const raw = this.buffer.slice(0, split);
      this.buffer = this.buffer.slice(split + 2);
      split = this.buffer.indexOf("\n\n");
      let id: string | null = null;
      const data: string[] = [];
      for (const line of raw.split("\n")) {
        if (line.startsWith("id:")) {
          id = line.slice(3).replace(/^ /, "");
        } else if (line.startsWith("data:")) {
          data.push(line.slice(5).replace(/^ /, ""));
        }
      }
      if (data.length > 0) {
        messages.push({ id, data: data.join("\n") });
      }
    }
    return messages;
  }
}

export async function* readSse(
  response: Response,
): AsyncGenerator<SseMessage> {
  if (!response.body) return;
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  const parser = new SseParser();
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      for (const message of parser.feed(
        decoder.decode(value, { stream: true }),
      )) {
        yield message;
      }
    }
  } finally {
    reader.releaseLock();
  }
}
