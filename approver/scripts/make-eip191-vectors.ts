import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { Wallet } from "ethers";
import { DmkApprovalDevice } from "../src/device.ts";
import { SpeculosDriver } from "../src/speculos.ts";

const FIXTURES = new URL("../../fixtures/", import.meta.url);
const OUT = fileURLToPath(new URL("eip191_vectors.json", FIXTURES));

const texts = (
  JSON.parse(
    readFileSync(new URL("approval_text_vectors.json", FIXTURES), "utf8"),
  ) as { text: string }[]
).map((v) => v.text);

const KEYS = [
  "0x" + "0".repeat(63) + "1",
  "0x" + "0".repeat(63) + "2",
  "0x" + "a".repeat(64),
];

type Vector = {
  message: string;
  signature: string;
  address: string;
  source: string;
};

async function main(): Promise<void> {
  const messages = [texts[0]!, texts[1]!, "satchel ledger approval demo"];
  const out: Vector[] = KEYS.map((key, i) => {
    const wallet = new Wallet(key);
    return {
      message: messages[i]!,
      signature: "",
      address: wallet.address,
      source: "ethers",
    };
  });
  for (const [i, key] of KEYS.entries()) {
    out[i]!.signature = await new Wallet(key).signMessage(out[i]!.message);
  }

  const device = new DmkApprovalDevice(120_000);
  const demo = new SpeculosDriver();
  try {
    const message = texts[2]!;
    const { address } = await device.address();
    const [sig] = await Promise.all([
      device.signPersonalMessage(message),
      demo.approveReview(),
    ]);
    const r = sig.r.slice(2).padStart(64, "0");
    const s = sig.s.slice(2).padStart(64, "0");
    const v = sig.v === 0 || sig.v === 1 ? sig.v + 27 : sig.v;
    out.push({
      message,
      signature: `0x${r}${s}${v.toString(16).padStart(2, "0")}`,
      address,
      source: "speculos",
    });
  } finally {
    await device.close();
  }

  writeFileSync(OUT, JSON.stringify(out, null, 2) + "\n");
  process.stderr.write(`wrote ${out.length} vectors to ${OUT}\n`);
  process.exit(0);
}

main().catch((err) => {
  process.stderr.write(`${(err as Error)?.message ?? err}\n`);
  process.exit(1);
});
