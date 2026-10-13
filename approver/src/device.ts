import {
  connect,
  currentAppName,
  DeviceStatus,
  dmk,
  isDeviceRejection,
  loadLedgerPackage,
  runAction,
  sessionState,
  stopTransportTimers,
  waitForReady,
} from "./dmk.ts";

const { SignerEthBuilder } = loadLedgerPackage<
  typeof import("@ledgerhq/device-signer-kit-ethereum")
>("@ledgerhq/device-signer-kit-ethereum");

const PATH = "44'/60'/0'/0/0";
const EXPECTED_APP = "Ethereum";

export interface ApprovalDevice {
  address(): Promise<{ address: string; path: string }>;
  signPersonalMessage(
    text: string,
  ): Promise<{ r: string; s: string; v: number }>;
}

export class DmkApprovalDevice implements ApprovalDevice {
  private sessionId: string | undefined;
  private readonly timeoutMs: number;
  private readonly path: string;

  constructor(timeoutMs = 60_000, path: string = PATH) {
    this.timeoutMs = timeoutMs;
    this.path = path;
  }

  private async ensureSession(): Promise<string> {
    if (this.sessionId !== undefined) {
      const state = await sessionState(this.sessionId).catch(() => undefined);
      if (state && state.deviceStatus !== DeviceStatus.NOT_CONNECTED) {
        return this.sessionId;
      }
      this.sessionId = undefined;
    }
    const id = await connect();
    const state = await waitForReady(id);
    const app = currentAppName(state);
    if (app !== EXPECTED_APP) {
      await dmk.disconnect({ sessionId: id }).catch(() => {});
      throw new Error(`expected the ${EXPECTED_APP} app, got ${app ?? "none"}`);
    }
    this.sessionId = id;
    return id;
  }

  async address(): Promise<{ address: string; path: string }> {
    const sessionId = await this.ensureSession();
    const signerEth = new SignerEthBuilder({ dmk, sessionId }).build();
    const output = await this.guard(
      runAction<{ address: string }>(
        signerEth.getAddress(this.path, { checkOnDevice: false }),
        this.timeoutMs,
      ),
    );
    return { address: output.address, path: this.path };
  }

  async signPersonalMessage(
    text: string,
  ): Promise<{ r: string; s: string; v: number }> {
    const sessionId = await this.ensureSession();
    const signerEth = new SignerEthBuilder({ dmk, sessionId }).build();
    return this.guard(
      runAction<{ r: string; s: string; v: number }>(
        signerEth.signMessage(this.path, text),
        this.timeoutMs,
      ),
    );
  }

  /**
   * A cancelled or failed action can leave the DMK session wedged (the next
   * exchange fails at once), so start the next request on a fresh session.
   * A rejection on the device is a normal answer and keeps the session.
   */
  private async guard<T>(action: Promise<T>): Promise<T> {
    try {
      return await action;
    } catch (err) {
      if (!isDeviceRejection(err)) await this.dropSession();
      throw err;
    }
  }

  private async dropSession(): Promise<void> {
    const sessionId = this.sessionId;
    this.sessionId = undefined;
    if (sessionId !== undefined) {
      await dmk.disconnect({ sessionId }).catch(() => {});
    }
  }

  async close(): Promise<void> {
    if (this.sessionId !== undefined) {
      await dmk.disconnect({ sessionId: this.sessionId }).catch(() => {});
      this.sessionId = undefined;
    }
    stopTransportTimers();
  }
}
