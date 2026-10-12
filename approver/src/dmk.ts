import { createRequire } from "node:module";
import { filter, firstValueFrom, timeout, type Observable } from "rxjs";
import type {
  DeviceManagementKit,
  DeviceSessionId,
  DeviceSessionState,
} from "@ledgerhq/device-management-kit";

/** The published @ledgerhq ESM builds use extensionless imports meant for bundlers; the CJS builds resolve natively. */
const require = createRequire(import.meta.url);

const {
  DeviceActionStatus,
  DeviceManagementKitBuilder,
  DeviceSessionStateType,
  DeviceStatus,
} = require("@ledgerhq/device-management-kit") as typeof import("@ledgerhq/device-management-kit");

const { speculosIdentifier, speculosTransportFactory } = require(
  "@ledgerhq/device-transport-kit-speculos",
) as typeof import("@ledgerhq/device-transport-kit-speculos");

export function loadLedgerPackage<T>(name: string): T {
  return require(name) as T;
}

export { DeviceActionStatus, DeviceStatus };

const SPECULOS_URL = process.env.SPECULOS_URL ?? "http://127.0.0.1:5001";

type SpeculosTransportInstance = {
  disconnectInterval?: ReturnType<typeof setInterval> | null;
};
let transportInstance: SpeculosTransportInstance | undefined;
const innerFactory = speculosTransportFactory(SPECULOS_URL);

/** One DMK instance per process, wired to the Speculos emulator transport. */
export const dmk: DeviceManagementKit = new DeviceManagementKitBuilder()
  .addTransport(
    (deps) =>
      (transportInstance = innerFactory(deps) as SpeculosTransportInstance) as never,
  )
  .build();

/** Clears the speculos transport's disconnect poll (leaked by disconnect() in 1.2.1). */
export function stopTransportTimers(): void {
  if (transportInstance?.disconnectInterval) {
    clearInterval(transportInstance.disconnectInterval);
    transportInstance.disconnectInterval = null;
  }
}

/** Discover the emulated device and open a session. */
export async function connect(timeoutMs = 15_000): Promise<DeviceSessionId> {
  const devices = await firstValueFrom(
    dmk
      .listenToAvailableDevices({ transport: speculosIdentifier })
      .pipe(
        filter((list) => list.length > 0),
        timeout({ first: timeoutMs }),
      ),
  );
  return dmk.connect({
    device: devices[0]!,
    sessionRefresherOptions: { isRefresherDisabled: false },
  });
}

/** First emission of the device session state. */
export async function sessionState(
  sessionId: DeviceSessionId,
  timeoutMs = 10_000,
): Promise<DeviceSessionState> {
  return firstValueFrom(
    dmk
      .getDeviceSessionState({ sessionId })
      .pipe(timeout({ first: timeoutMs })),
  );
}

/** Wait until the session reports a ready state with an app name available. */
export async function waitForReady(
  sessionId: DeviceSessionId,
  timeoutMs = 10_000,
): Promise<DeviceSessionState> {
  return firstValueFrom(
    dmk.getDeviceSessionState({ sessionId }).pipe(
      filter(
        (state) =>
          state.deviceStatus === DeviceStatus.CONNECTED &&
          state.sessionStateType !== DeviceSessionStateType.Connected,
      ),
      timeout({ first: timeoutMs }),
    ),
  );
}

/** The name of the currently running app (e.g. "Ethereum"). */
export function currentAppName(state: DeviceSessionState): string | undefined {
  return state.sessionStateType === DeviceSessionStateType.Connected
    ? undefined
    : state.currentApp.name;
}

export class DeviceActionTimeout extends Error {
  constructor(timeoutMs: number) {
    super(`Device action timed out after ${timeoutMs}ms`);
    this.name = "DeviceActionTimeout";
  }
}

type DeviceActionEmission<Output> = {
  status: (typeof DeviceActionStatus)[keyof typeof DeviceActionStatus];
  output?: Output;
  error?: unknown;
};

/** Run a device action observable to completion with a timeout. */
export function runAction<Output>(
  action: {
    observable: Observable<DeviceActionEmission<Output>>;
    cancel: () => void;
  },
  timeoutMs = 60_000,
): Promise<Output> {
  return new Promise<Output>((resolve, reject) => {
    const timer = setTimeout(() => {
      action.cancel();
      reject(new DeviceActionTimeout(timeoutMs));
    }, timeoutMs);
    const sub = action.observable.subscribe({
      next: (state) => {
        if (state.status === DeviceActionStatus.Completed) {
          clearTimeout(timer);
          sub.unsubscribe();
          resolve(state.output as Output);
        } else if (state.status === DeviceActionStatus.Error) {
          clearTimeout(timer);
          sub.unsubscribe();
          reject(state.error);
        } else if (state.status === DeviceActionStatus.Stopped) {
          clearTimeout(timer);
          sub.unsubscribe();
          reject(new Error("Device action stopped"));
        }
      },
      error: (err: unknown) => {
        clearTimeout(timer);
        reject(err);
      },
    });
  });
}

type TaggedError = {
  _tag?: string;
  errorCode?: string;
  originalError?: { errorCode?: string };
};

/** True when the error is a user rejection on the device, not a real failure. */
export function isDeviceRejection(error: unknown): boolean {
  const e = error as TaggedError | undefined;
  const tag = e?._tag ?? "";
  const code = e?.errorCode ?? e?.originalError?.errorCode ?? "";
  return (
    tag === "RefusedByUserDAError" ||
    code === "5501" ||
    code === "6985" ||
    code === "6982"
  );
}
