import { act, type ComponentProps } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  MicrophoneCheckDialog,
  type MicrophoneDialogState,
} from "./MicrophoneCheckDialog";

const result = {
  deviceLabel: "Studio USB Mic",
  peakLevel: 0.05,
  signalDetected: true,
};

describe("MicrophoneCheckDialog", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    vi.restoreAllMocks();
  });

  async function renderDialog(
    state: MicrophoneDialogState,
    overrides: Partial<ComponentProps<typeof MicrophoneCheckDialog>> = {},
  ) {
    const props: ComponentProps<typeof MicrophoneCheckDialog> = {
      open: true,
      state,
      result: state === "ready" || state === "quiet" ? result : null,
      errorMessage: state === "error" ? "权限被拒绝" : null,
      level: state === "ready" ? 0.05 : 0,
      doNotRemind: false,
      onDoNotRemindChange: vi.fn(),
      onCheck: vi.fn(),
      onConfirm: vi.fn(),
      onClose: vi.fn(),
      ...overrides,
    };
    await act(async () => root.render(<MicrophoneCheckDialog {...props} />));
    return props;
  }

  it("renders nothing while closed", async () => {
    await act(async () =>
      root.render(
        <MicrophoneCheckDialog
          open={false}
          state="idle"
          result={null}
          errorMessage={null}
          level={0}
          doNotRemind={false}
          onDoNotRemindChange={vi.fn()}
          onCheck={vi.fn()}
          onConfirm={vi.fn()}
          onClose={vi.fn()}
        />,
      ),
    );
    expect(container.querySelector('[role="dialog"]')).toBeNull();
  });

  it("requires an explicit check before showing start and reminder controls", async () => {
    const props = await renderDialog("idle");
    expect(container.querySelector('[role="dialog"]')).not.toBeNull();
    expect(buttonNamed("检查麦克风")).toBe(document.activeElement);
    expect(buttonNamed("开始练唱")).toBeNull();
    expect(container.querySelector('input[type="checkbox"]')).toBeNull();

    await act(async () => buttonNamed("检查麦克风")?.click());
    expect(props.onCheck).toHaveBeenCalledOnce();
  });

  it("shows quiet as a successful live-track state and can persist the choice", async () => {
    const onDoNotRemindChange = vi.fn();
    const onConfirm = vi.fn();
    await renderDialog("quiet", {
      result: { ...result, peakLevel: 0, signalDetected: false },
      onDoNotRemindChange,
      onConfirm,
    });

    expect(container.textContent).toContain("麦克风已连接");
    expect(container.textContent).toContain("环境较安静，可以继续");
    const checkbox = container.querySelector<HTMLInputElement>('input[type="checkbox"]');
    await act(async () => checkbox?.click());
    expect(onDoNotRemindChange).toHaveBeenCalledWith(true);
    await act(async () => buttonNamed("开始练唱")?.click());
    expect(onConfirm).toHaveBeenCalledOnce();
  });

  it("moves focus to cancel while checking and reports errors without enabling start", async () => {
    await renderDialog("checking");
    expect(buttonNamed("取消麦克风检查")).toBe(document.activeElement);
    expect(buttonNamed("检查中")?.disabled).toBe(true);

    await renderDialog("error", { errorMessage: "麦克风权限被拒绝" });
    expect(container.textContent).toContain("麦克风权限被拒绝");
    expect(buttonNamed("重新检查")).toBe(document.activeElement);
    expect(buttonNamed("开始练唱")).toBeNull();
  });

  it("closes on Escape and traps forward focus inside the dialog", async () => {
    const onClose = vi.fn();
    await renderDialog("ready", { onClose });
    const dialog = container.querySelector<HTMLElement>('[role="dialog"]');
    expect(buttonNamed("开始练唱")).toBe(document.activeElement);

    const escapeEvent = new KeyboardEvent("keydown", {
      key: "Escape",
      code: "Escape",
      bubbles: true,
      cancelable: true,
    });
    await act(async () => {
      buttonNamed("开始练唱")?.dispatchEvent(escapeEvent);
    });
    expect(onClose).toHaveBeenCalledOnce();
    onClose.mockClear();
    const focusable = Array.from(
      dialog?.querySelectorAll<HTMLElement>(
        ':is(button:not(:disabled), input:not(:disabled), [href], [tabindex]:not([tabindex="-1"]))',
      ) ?? [],
    );
    expect(focusable.at(-1)).toBe(buttonNamed("开始练唱"));

    const tabEvent = new KeyboardEvent("keydown", {
      key: "Tab",
      code: "Tab",
      bubbles: true,
      cancelable: true,
    });
    Object.defineProperties(tabEvent, {
      keyCode: { value: 9 },
      which: { value: 9 },
    });
    await act(async () => {
      buttonNamed("开始练唱")?.dispatchEvent(tabEvent);
    });
    expect(tabEvent.defaultPrevented).toBe(true);
    expect(buttonNamed("取消麦克风检查")).toBe(document.activeElement);

    await act(async () => dialog?.dispatchEvent(escapeEvent));
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("exposes a bounded accessible input meter", async () => {
    await renderDialog("ready", { level: 0.05 });
    const meter = container.querySelector<HTMLElement>('[role="meter"]');
    expect(meter?.getAttribute("aria-valuenow")).toBe("40");
    expect(meter?.querySelector<HTMLElement>("span")?.style.width).toBe("40%");
  });

  function buttonNamed(name: string): HTMLButtonElement | null {
    return (
      Array.from(container.querySelectorAll("button")).find(
        (button) => button.textContent?.trim() === name || button.getAttribute("aria-label") === name,
      ) ?? null
    );
  }
});
