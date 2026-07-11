import { describe, expect, it, vi } from "vitest";

import {
  MICROPHONE_CHECK_SKIP_KEY,
  readMicrophoneCheckSkipped,
  writeMicrophoneCheckSkipped,
} from "./microphonePreference";

function memoryStorage(initial?: string) {
  const values = new Map<string, string>();
  if (initial !== undefined) values.set(MICROPHONE_CHECK_SKIP_KEY, initial);
  return {
    values,
    getItem: vi.fn((key: string) => values.get(key) ?? null),
    setItem: vi.fn((key: string, value: string) => values.set(key, value)),
    removeItem: vi.fn((key: string) => values.delete(key)),
  };
}

describe("microphone check preference", () => {
  it("defaults to checking when no versioned preference exists", () => {
    expect(readMicrophoneCheckSkipped(memoryStorage())).toBe(false);
  });

  it("only recognizes the exact v1 skip value", () => {
    expect(readMicrophoneCheckSkipped(memoryStorage("1"))).toBe(true);
    expect(readMicrophoneCheckSkipped(memoryStorage("true"))).toBe(false);
  });

  it("persists skip and removes it when checks are restored", () => {
    const storage = memoryStorage();
    expect(writeMicrophoneCheckSkipped(true, storage)).toBe(true);
    expect(storage.values.get(MICROPHONE_CHECK_SKIP_KEY)).toBe("1");
    expect(writeMicrophoneCheckSkipped(false, storage)).toBe(true);
    expect(storage.values.has(MICROPHONE_CHECK_SKIP_KEY)).toBe(false);
  });

  it("fails closed when browser storage is unavailable", () => {
    const storage = {
      getItem: vi.fn(() => {
        throw new DOMException("blocked", "SecurityError");
      }),
      setItem: vi.fn(() => {
        throw new DOMException("blocked", "SecurityError");
      }),
      removeItem: vi.fn(() => {
        throw new DOMException("blocked", "SecurityError");
      }),
    };
    expect(readMicrophoneCheckSkipped(storage)).toBe(false);
    expect(writeMicrophoneCheckSkipped(true, storage)).toBe(false);
  });

  it("fails closed when accessing window.localStorage itself throws", () => {
    const descriptor = Object.getOwnPropertyDescriptor(window, "localStorage");
    Object.defineProperty(window, "localStorage", {
      configurable: true,
      get() {
        throw new DOMException("blocked", "SecurityError");
      },
    });
    try {
      expect(readMicrophoneCheckSkipped()).toBe(false);
      expect(writeMicrophoneCheckSkipped(true)).toBe(false);
    } finally {
      if (descriptor) Object.defineProperty(window, "localStorage", descriptor);
    }
  });
});
