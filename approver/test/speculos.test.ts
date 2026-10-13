import assert from "node:assert/strict";
import { createServer, type Server } from "node:http";
import { after, before, describe, it } from "node:test";
import { isHomeScreen, ReviewGone, SpeculosDriver } from "../src/speculos.ts";

const HOME = ["Ethereum", "This app enables signing", "Quit app"];

/** A fake Speculos: serves a scripted run of screens and records finger calls. */
function fakeSpeculos(screens: string[][]) {
  const fingers: Record<string, unknown>[] = [];
  let i = 0;
  const server = createServer((req, res) => {
    if (req.url?.startsWith("/events")) {
      const texts = screens[Math.min(i++, screens.length - 1)];
      res.writeHead(200, { "content-type": "application/json" });
      res.end(JSON.stringify({ events: texts.map((text) => ({ text, x: 10, y: 10, w: 100, h: 40 })) }));
      return;
    }
    let body = "";
    req.on("data", (c) => (body += c));
    req.on("end", () => {
      fingers.push(JSON.parse(body || "{}"));
      res.writeHead(200, { "content-type": "application/json" });
      res.end("{}");
    });
  });
  return { server, fingers };
}

async function listen(server: Server): Promise<string> {
  await new Promise<void>((r) => server.listen(0, "127.0.0.1", r));
  return `http://127.0.0.1:${(server.address() as { port: number }).port}`;
}

describe("speculos review automation", () => {
  it("recognises the app's home screen", () => {
    assert.ok(isHomeScreen(HOME.map((text) => ({ text }))));
    assert.ok(!isHomeScreen([{ text: "Message" }, { text: "Reject" }]));
  });

  describe("waiting for the review", () => {
    const fake = fakeSpeculos([HOME, HOME, [], ["Hold to sign message"]]);
    let base = "";
    before(async () => {
      base = await listen(fake.server);
    });
    after(() => fake.server.close());

    it("waits on the home screen instead of swiping it, then holds", async () => {
      await new SpeculosDriver(base).approveReview({ stillPending: () => true });
      assert.deepEqual(
        fake.fingers.map((f) => f.action),
        ["press", "release"],
        "no swipes on the home screen",
      );
    });
  });

  describe("a decided request", () => {
    const fake = fakeSpeculos([HOME]);
    let base = "";
    before(async () => {
      base = await listen(fake.server);
    });
    after(() => fake.server.close());

    it("stops with ReviewGone and never touches the screen", async () => {
      await assert.rejects(
        new SpeculosDriver(base).rejectReview({ stillPending: () => false }),
        ReviewGone,
      );
      assert.deepEqual(fake.fingers, []);
    });

    it("a review that never arrives is a device error, not a decision", async () => {
      await assert.rejects(
        new SpeculosDriver(base).approveReview({ stillPending: () => true, reviewWaitMs: 200 }),
        (err: Error) => !(err instanceof ReviewGone) && /never reached/.test(err.message),
      );
      assert.deepEqual(fake.fingers, []);
    });
  });
});
