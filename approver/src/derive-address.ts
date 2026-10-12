import {
  connect,
  currentAppName,
  dmk,
  isDeviceRejection,
  loadLedgerPackage,
  runAction,
  waitForReady,
} from "./dmk.ts";

const { SignerEthBuilder } = loadLedgerPackage<
  typeof import("@ledgerhq/device-signer-kit-ethereum")
>("@ledgerhq/device-signer-kit-ethereum");

const PATH = "44'/60'/0'/0/0";
const EXPECTED_APP = "Ethereum";

async function main(): Promise<void> {
  process.stderr.write("connecting to Speculos…\n");
  const sessionId = await connect();
  try {
    const state = await waitForReady(sessionId);
    const app = currentAppName(state);
    if (app !== EXPECTED_APP) {
      throw new Error(`expected the ${EXPECTED_APP} app, got ${app ?? "none"}`);
    }
    process.stderr.write(`session ready; app=${app}\n`);
    const signerEth = new SignerEthBuilder({ dmk, sessionId }).build();
    const output = await runAction<{ address: string; publicKey: string }>(
      signerEth.getAddress(PATH, { checkOnDevice: false }),
    );
    process.stdout.write(
      `${JSON.stringify({ address: output.address, path: PATH })}\n`,
    );
  } finally {
    await dmk.disconnect({ sessionId });
  }
  process.exit(0);
}

main().catch((err: unknown) => {
  if (isDeviceRejection(err)) {
    process.stderr.write("rejected on device\n");
  } else {
    process.stderr.write(`${(err as Error)?.message ?? err}\n`);
  }
  process.exit(1);
});
