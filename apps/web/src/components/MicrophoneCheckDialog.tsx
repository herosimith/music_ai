"use client";

import { Activity, CheckCircle2, Mic, MicOff, RotateCcw, X } from "lucide-react";
import {
  type KeyboardEvent as ReactKeyboardEvent,
  useEffect,
  useRef,
} from "react";

import type { MicrophoneCheckResult } from "@/lib/microphoneCheck";

export type MicrophoneDialogState = "checking" | "error" | "idle" | "quiet" | "ready";

interface MicrophoneCheckDialogProps {
  open: boolean;
  state: MicrophoneDialogState;
  result: MicrophoneCheckResult | null;
  errorMessage: string | null;
  level: number;
  doNotRemind: boolean;
  onDoNotRemindChange: (value: boolean) => void;
  onCheck: () => void;
  onConfirm: () => void;
  onClose: () => void;
}

export function MicrophoneCheckDialog({
  open,
  state,
  result,
  errorMessage,
  level,
  doNotRemind,
  onDoNotRemindChange,
  onCheck,
  onConfirm,
  onClose,
}: MicrophoneCheckDialogProps) {
  const primaryAction = useRef<HTMLButtonElement>(null);
  const closeAction = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    if (state === "checking") closeAction.current?.focus();
    else primaryAction.current?.focus();
  }, [open, state]);

  if (!open) return null;
  const complete = state === "quiet" || state === "ready";
  const displayLevel = Math.round(Math.min(1, Math.max(0, level) * 8) * 100);
  const copy = microphoneStateCopy(state, result, errorMessage);

  const onKeyDown = (event: ReactKeyboardEvent<HTMLElement>) => {
    if (event.key === "Escape") {
      event.preventDefault();
      onClose();
      return;
    }
    if (event.key !== "Tab") return;
    const focusable = Array.from(
      event.currentTarget.querySelectorAll<HTMLElement>(
        ':is(button:not(:disabled), input:not(:disabled), [href], [tabindex]:not([tabindex="-1"]))',
      ),
    );
    if (focusable.length === 0) {
      event.preventDefault();
      return;
    }
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    const active = event.target instanceof HTMLElement ? event.target : document.activeElement;
    if (event.shiftKey && active === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && active === last) {
      event.preventDefault();
      first.focus();
    }
  };

  return (
    <div className="dialog-backdrop" role="presentation" onMouseDown={onClose}>
      <section
        className="microphone-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="microphone-check-title"
        aria-describedby="microphone-check-detail"
        onKeyDown={onKeyDown}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="dialog-header">
          <div>
            <span className="section-label">INPUT CHECK</span>
            <h2 id="microphone-check-title">检查麦克风</h2>
          </div>
          <button
            ref={closeAction}
            className="icon-button"
            title="取消"
            aria-label="取消麦克风检查"
            onClick={onClose}
          >
            <X size={18} />
          </button>
        </div>

        <div className="microphone-check-body">
          <div className={`microphone-check-status ${state}`} aria-live="polite">
            <span className="microphone-check-icon" aria-hidden="true">
              {state === "error" ? (
                <MicOff size={25} />
              ) : complete ? (
                <CheckCircle2 size={25} />
              ) : state === "checking" ? (
                <Activity size={25} />
              ) : (
                <Mic size={25} />
              )}
            </span>
            <div>
              <strong>{copy.title}</strong>
              <span id="microphone-check-detail">{copy.detail}</span>
            </div>
          </div>

          <div className="microphone-level-row">
            <span>输入电平</span>
            <div
              className="microphone-level-track"
              role="meter"
              aria-label="麦克风输入电平"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={displayLevel}
            >
              <span style={{ width: `${displayLevel}%` }} />
            </div>
            <strong>{displayLevel}%</strong>
          </div>

          {complete && (
            <label className="rights-check microphone-reminder-check">
              <input
                type="checkbox"
                checked={doNotRemind}
                onChange={(event) => onDoNotRemindChange(event.target.checked)}
              />
              <span>以后不再提醒</span>
            </label>
          )}
        </div>

        <div className="microphone-dialog-actions">
          <button className="button secondary" onClick={onClose}>
            取消
          </button>
          {complete ? (
            <>
              <button className="icon-text-button" onClick={onCheck}>
                <RotateCcw size={16} />
                重新检查
              </button>
              <button ref={primaryAction} className="button record" onClick={onConfirm}>
                <Mic size={17} />
                开始练唱
              </button>
            </>
          ) : (
            <button
              ref={primaryAction}
              className="button primary"
              disabled={state === "checking"}
              onClick={onCheck}
            >
              {state === "checking" ? <Activity size={17} /> : <Mic size={17} />}
              {state === "checking" ? "检查中" : state === "error" ? "重新检查" : "检查麦克风"}
            </button>
          )}
        </div>
      </section>
    </div>
  );
}

function microphoneStateCopy(
  state: MicrophoneDialogState,
  result: MicrophoneCheckResult | null,
  errorMessage: string | null,
): { title: string; detail: string } {
  switch (state) {
    case "checking":
      return { title: "正在检查", detail: "正在确认麦克风权限与实时音轨。" };
    case "ready":
      return {
        title: "麦克风可用",
        detail: `${result?.deviceLabel ?? "默认麦克风"} · 已检测到输入声音`,
      };
    case "quiet":
      return {
        title: "麦克风已连接",
        detail: `${result?.deviceLabel ?? "默认麦克风"} · 环境较安静，可以继续`,
      };
    case "error":
      return { title: "检查未通过", detail: errorMessage ?? "无法启动麦克风。" };
    case "idle":
      return { title: "准备检查", detail: "检查完成前不会播放歌曲或开始录音。" };
  }
}
