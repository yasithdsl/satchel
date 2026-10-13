import { DmkApprovalDevice } from "./device.ts";
import { SpeculosDriver } from "./speculos.ts";
import { createServer } from "./server.ts";

const PORT = Number(process.env.APPROVER_PORT ?? 8003);
const DEMO_AUTOMATION = /^(1|true|yes)$/i.test(
  process.env.SATCHEL_APPROVER_DEMO_AUTOMATION ?? "",
);

// Long enough for a presenter to talk through the Ledger screen; the laptop
// waits up to 180 s for an answer, so this must stay below that.
const APPROVAL_TIMEOUT_MS = Number(process.env.APPROVER_TIMEOUT_MS ?? 150_000);

const device = new DmkApprovalDevice(APPROVAL_TIMEOUT_MS);
const demo = DEMO_AUTOMATION ? new SpeculosDriver() : null;
const server = createServer({
  device,
  demo,
  demoAutomation: DEMO_AUTOMATION,
});

server.listen(PORT, "127.0.0.1", () => {
  process.stderr.write(`approver listening on 127.0.0.1:${PORT}\n`);
});
