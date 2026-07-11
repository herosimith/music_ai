export const MICROPHONE_CHECK_SKIP_KEY = "music-ai.microphone-check.skip.v1";

type StorageLike = Pick<Storage, "getItem" | "removeItem" | "setItem">;

export function readMicrophoneCheckSkipped(storage?: StorageLike): boolean {
  try {
    return resolveStorage(storage)?.getItem(MICROPHONE_CHECK_SKIP_KEY) === "1";
  } catch {
    return false;
  }
}

export function writeMicrophoneCheckSkipped(
  skipped: boolean,
  storage?: StorageLike,
): boolean {
  try {
    const target = resolveStorage(storage);
    if (!target) return false;
    if (skipped) target.setItem(MICROPHONE_CHECK_SKIP_KEY, "1");
    else target.removeItem(MICROPHONE_CHECK_SKIP_KEY);
    return true;
  } catch {
    return false;
  }
}

function resolveStorage(storage?: StorageLike): StorageLike | null {
  if (storage) return storage;
  if (typeof window === "undefined") return null;
  return window.localStorage;
}
