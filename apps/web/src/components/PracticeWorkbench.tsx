"use client";

import {
  Activity,
  AudioLines,
  CheckCircle2,
  Clock3,
  Download,
  FileAudio,
  Gauge,
  History,
  Mic,
  MicOff,
  Music2,
  Pause,
  Play,
  RotateCcw,
  Settings2,
  SlidersHorizontal,
  Sparkles,
  Square,
  Upload,
  Volume2,
  WandSparkles,
  X,
} from "lucide-react";
import {
  type ChangeEvent,
  type KeyboardEvent as ReactKeyboardEvent,
  type ReactNode,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import type WaveSurfer from "wavesurfer.js";

import { type LocalAnalysis, analyzeTake } from "@/lib/analysis";
import {
  createDemoAudio,
  decodeAudioBlob,
  encodeMonoWav,
  formatTime,
  resampleLinear,
  sliceSamples,
} from "@/lib/audio";
import { MicrophoneCapture } from "@/lib/capture";
import {
  capturePlaybackAnchor,
  captureStartSampleIndex,
  TransportRecorder,
  type TransportPoint,
} from "@/lib/transport";

type ViewName = "practice" | "history";
type SessionState = "idle" | "arming" | "recording" | "analyzing" | "ready" | "error";

interface SongSource {
  name: string;
  blob: Blob;
  url: string;
  isDemo: boolean;
  demoReference?: Float32Array;
  demoUser?: Float32Array;
  demoSampleRate?: number;
}

interface HistoryEntry {
  id: string;
  songName: string;
  createdAt: Date;
  analysis: LocalAnalysis;
}

interface LastCapture {
  samples: Float32Array;
  sampleRate: number;
  transport: TransportPoint[];
}

const MAX_FILE_BYTES = 100_000_000;

export function PracticeWorkbench() {
  const [view, setView] = useState<ViewName>("practice");
  const [song, setSong] = useState<SongSource | null>(null);
  const [duration, setDuration] = useState(0);
  const [currentTime, setCurrentTime] = useState(0);
  const [selectionStart, setSelectionStart] = useState(0);
  const [selectionEnd, setSelectionEnd] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const [rightsAccepted, setRightsAccepted] = useState(false);
  const [sessionState, setSessionState] = useState<SessionState>("idle");
  const [analysis, setAnalysis] = useState<LocalAnalysis | null>(null);
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [lastCapture, setLastCapture] = useState<LastCapture | null>(null);
  const waveformElement = useRef<HTMLDivElement>(null);
  const waveform = useRef<WaveSurfer | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const capture = useRef<MicrophoneCapture | null>(null);
  const transport = useRef<TransportRecorder | null>(null);
  const transportTimer = useRef<number | null>(null);
  const recordingRef = useRef(false);
  const mountedRef = useRef(true);
  const settingsCloseButton = useRef<HTMLButtonElement>(null);
  const settingsReturnFocus = useRef<HTMLElement | null>(null);
  const stopSessionRef = useRef<() => Promise<void>>(async () => undefined);
  const selectionRef = useRef({ start: 0, end: 0 });

  useEffect(() => {
    selectionRef.current = { start: selectionStart, end: selectionEnd };
  }, [selectionStart, selectionEnd]);

  useEffect(() => {
    recordingRef.current = sessionState === "recording";
  }, [sessionState]);

  useEffect(() => {
    if (settingsOpen) settingsCloseButton.current?.focus();
  }, [settingsOpen]);

  useEffect(() => {
    if (!song || !waveformElement.current) return;
    let disposed = false;
    let instance: WaveSurfer | null = null;
    void import("wavesurfer.js").then(({ default: WaveSurferConstructor }) => {
      if (disposed || !waveformElement.current) return;
      instance = WaveSurferConstructor.create({
        container: waveformElement.current,
        url: song.url,
        height: 148,
        waveColor: "#8fa29a",
        progressColor: "#e65f52",
        cursorColor: "#17201c",
        cursorWidth: 1,
        barWidth: 2,
        barGap: 2,
        barRadius: 1,
        normalize: true,
        dragToSeek: true,
      });
      waveform.current = instance;
      instance.on("ready", (loadedDuration) => {
        setDuration(loadedDuration);
        setSelectionStart(0);
        setSelectionEnd(loadedDuration);
        setCurrentTime(0);
      });
      instance.on("timeupdate", (time) => {
        setCurrentTime(time);
        if (recordingRef.current && time >= selectionRef.current.end) {
          void stopSessionRef.current();
        }
      });
      instance.on("play", () => setIsPlaying(true));
      instance.on("pause", () => setIsPlaying(false));
      instance.on("finish", () => setIsPlaying(false));
    });
    return () => {
      disposed = true;
      if (waveform.current === instance) waveform.current = null;
      instance?.destroy();
    };
  }, [song]);

  useEffect(() => {
    return () => {
      if (song?.url) URL.revokeObjectURL(song.url);
    };
  }, [song]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      if (transportTimer.current !== null) window.clearInterval(transportTimer.current);
      const activeCapture = capture.current;
      capture.current = null;
      transport.current = null;
      recordingRef.current = false;
      void activeCapture?.stop();
    };
  }, []);

  const setSongBlob = useCallback(
    (blob: Blob, name: string, demo?: ReturnType<typeof createDemoAudio>) => {
      const url = URL.createObjectURL(blob);
      setSong({
        name,
        blob,
        url,
        isDemo: Boolean(demo),
        demoReference: demo?.referenceSamples,
        demoUser: demo?.userSamples,
        demoSampleRate: demo?.sampleRate,
      });
      setAnalysis(null);
      setLastCapture(null);
      setErrorMessage(null);
      setSessionState("idle");
    },
    [],
  );

  const loadDemo = useCallback(() => {
    const demo = createDemoAudio();
    setSongBlob(demo.blob, "合成练习旋律 · A3–D4", demo);
    setRightsAccepted(true);
  }, [setSongBlob]);

  const onFileSelected = useCallback(
    (event: ChangeEvent<HTMLInputElement>) => {
      const file = event.target.files?.[0];
      event.target.value = "";
      if (!file) return;
      if (!file.type.startsWith("audio/")) {
        setErrorMessage("请选择浏览器支持的音频文件。");
        return;
      }
      if (file.size > MAX_FILE_BYTES) {
        setErrorMessage("音频文件不能超过 100 MB。");
        return;
      }
      setSongBlob(file, file.name);
      setRightsAccepted(false);
    },
    [setSongBlob],
  );

  const addHistory = useCallback(
    (nextAnalysis: LocalAnalysis, sourceName?: string) => {
      setHistory((entries) => [
        {
          id: `${Date.now()}-${entries.length}`,
          songName: sourceName ?? song?.name ?? "未命名练习",
          createdAt: new Date(),
          analysis: nextAnalysis,
        },
        ...entries,
      ]);
    },
    [song?.name],
  );

  const runDemoAnalysis = useCallback(() => {
    const demo = createDemoAudio();
    if (!song?.isDemo) {
      setSongBlob(demo.blob, "合成练习旋律 · A3–D4", demo);
      setRightsAccepted(true);
    }
    setSessionState("analyzing");
    const nextAnalysis = analyzeTake(
      demo.referenceSamples,
      demo.userSamples,
      demo.sampleRate,
    );
    setAnalysis(nextAnalysis);
    setSessionState("ready");
    addHistory(nextAnalysis, "合成练习旋律 · A3–D4");
  }, [addHistory, setSongBlob, song?.isDemo]);

  const stopSession = useCallback(async () => {
    if (!recordingRef.current || !capture.current) return;
    recordingRef.current = false;
    setSessionState("analyzing");
    waveform.current?.pause();
    if (transportTimer.current !== null) {
      window.clearInterval(transportTimer.current);
      transportTimer.current = null;
    }
    transport.current?.capture(
      waveform.current?.getCurrentTime() ?? selectionRef.current.end,
      capture.current.capturedSamples,
    );
    try {
      const captured = await capture.current.stop();
      const points = transport.current?.snapshot() ?? [];
      setLastCapture({ ...captured, transport: points });
      if (!song) throw new Error("song source is missing");
      const decoded = await decodeAudioBlob(song.blob);
      const reference = sliceSamples(
        decoded.samples,
        decoded.sampleRate,
        selectionRef.current.start,
        selectionRef.current.end,
      );
      const normalizedReference = resampleLinear(
        reference,
        decoded.sampleRate,
        captured.sampleRate,
      );
      const alignedUser = captured.samples.slice(
        Math.min(captured.samples.length, captureStartSampleIndex(points)),
      );
      const nextAnalysis = analyzeTake(
        normalizedReference,
        alignedUser,
        captured.sampleRate,
      );
      setAnalysis(nextAnalysis);
      setSessionState("ready");
      addHistory(nextAnalysis);
    } catch {
      setSessionState("error");
      setErrorMessage("录音已停止，但本地预览分析失败。");
    } finally {
      capture.current = null;
      transport.current = null;
    }
  }, [addHistory, song]);

  useEffect(() => {
    stopSessionRef.current = stopSession;
  }, [stopSession]);

  const startSession = useCallback(async () => {
    const playback = waveform.current;
    if (!song || !playback || !rightsAccepted || selectionEnd - selectionStart < 0.5) return;
    playback.pause();
    playback.setTime(selectionStart);
    setErrorMessage(null);
    setSessionState("arming");
    const nextCapture = new MicrophoneCapture();
    try {
      await nextCapture.start();
      if (!mountedRef.current || waveform.current !== playback) {
        await nextCapture.stop();
        return;
      }
      capture.current = nextCapture;
      const nextTransport = new TransportRecorder(nextCapture.sampleRate);
      transport.current = nextTransport;
      await capturePlaybackAnchor(
        nextTransport,
        () => playback.play(),
        () => playback.getCurrentTime(),
        () => nextCapture.capturedSamples,
      );
      if (!mountedRef.current || capture.current !== nextCapture) {
        await nextCapture.stop();
        return;
      }
      transportTimer.current = window.setInterval(() => {
        if (!capture.current || !transport.current) return;
        transport.current.capture(
          waveform.current?.getCurrentTime() ?? selectionStart,
          capture.current.capturedSamples,
        );
      }, 250);
      recordingRef.current = true;
      setSessionState("recording");
    } catch {
      if (transportTimer.current !== null) {
        window.clearInterval(transportTimer.current);
        transportTimer.current = null;
      }
      recordingRef.current = false;
      transport.current = null;
      await nextCapture.stop().catch(() => undefined);
      if (!mountedRef.current) return;
      setSessionState("error");
      setErrorMessage("无法使用麦克风。请允许浏览器访问麦克风后重试。");
      capture.current = null;
    }
  }, [rightsAccepted, selectionEnd, selectionStart, song]);

  const togglePlayback = useCallback(() => {
    if (!waveform.current || sessionState === "recording") return;
    if (!isPlaying && currentTime >= selectionEnd) waveform.current.setTime(selectionStart);
    void waveform.current.playPause();
  }, [currentTime, isPlaying, selectionEnd, selectionStart, sessionState]);

  const resetPlayback = useCallback(() => {
    waveform.current?.pause();
    waveform.current?.setTime(selectionStart);
  }, [selectionStart]);

  const downloadCapture = useCallback(() => {
    if (!lastCapture) return;
    const blob = encodeMonoWav(lastCapture.samples, lastCapture.sampleRate);
    downloadBlob(blob, `music-ai-take-${Date.now()}.wav`);
  }, [lastCapture]);

  const downloadEvidence = useCallback(() => {
    if (!lastCapture) return;
    downloadBlob(
      new Blob([JSON.stringify(lastCapture.transport, null, 2)], {
        type: "application/json",
      }),
      `music-ai-transport-${Date.now()}.json`,
    );
  }, [lastCapture]);

  const openSettings = useCallback(() => {
    settingsReturnFocus.current =
      document.activeElement instanceof HTMLElement ? document.activeElement : null;
    setSettingsOpen(true);
  }, []);

  const closeSettings = useCallback(() => {
    setSettingsOpen(false);
    window.requestAnimationFrame(() => settingsReturnFocus.current?.focus());
  }, []);

  const onSettingsKeyDown = useCallback(
    (event: ReactKeyboardEvent<HTMLElement>) => {
      if (event.key === "Escape") {
        event.preventDefault();
        closeSettings();
        return;
      }
      if (event.key !== "Tab") return;
      const focusable = Array.from(
        event.currentTarget.querySelectorAll<HTMLElement>(
          'button:not(:disabled), [href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex="-1"])',
        ),
      );
      if (focusable.length === 0) {
        event.preventDefault();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    },
    [closeSettings],
  );

  const selectStart = (value: number) => {
    const next = Math.max(0, Math.min(value, selectionEnd - 0.5));
    setSelectionStart(next);
  };
  const selectEnd = (value: number) => {
    const next = Math.min(duration, Math.max(value, selectionStart + 0.5));
    setSelectionEnd(next);
  };

  const status = sessionStatus(sessionState);
  const selectedDuration = Math.max(0, selectionEnd - selectionStart);
  const overlayLeft = duration > 0 ? (selectionStart / duration) * 100 : 0;
  const overlayWidth = duration > 0 ? (selectedDuration / duration) * 100 : 0;
  const sourceLocked =
    sessionState === "arming" || sessionState === "recording" || sessionState === "analyzing";

  return (
    <div className="app-shell">
      <aside className="side-rail" aria-label="主导航">
        <button className="brand-mark" title="声准" onClick={() => setView("practice")}>
          <AudioLines size={25} strokeWidth={2.2} />
          <span>声准</span>
        </button>
        <nav className="rail-nav">
          <button
            className={view === "practice" ? "rail-button active" : "rail-button"}
            title="练唱工作台"
            aria-label="练唱工作台"
            onClick={() => setView("practice")}
          >
            <Mic size={21} />
          </button>
          <button
            className={view === "history" ? "rail-button active" : "rail-button"}
            title="练习记录"
            aria-label="练习记录"
            onClick={() => setView("history")}
          >
            <History size={21} />
            {history.length > 0 && <span className="rail-count">{history.length}</span>}
          </button>
        </nav>
        <button
          className="rail-button rail-settings"
          title="偏好设置"
          aria-label="偏好设置"
          onClick={openSettings}
        >
          <Settings2 size={21} />
        </button>
      </aside>

      <main className="workspace">
        <header className="workspace-header">
          <div>
            <p className="workspace-kicker">MUSIC_AI / PRACTICE</p>
            <h1>{view === "practice" ? "练唱工作台" : "练习记录"}</h1>
          </div>
          <div className="header-status">
            <span className="status-dot" aria-hidden="true" />
            <span>本地预览</span>
            <span className="header-divider" />
            <span>原始录音不离开浏览器</span>
          </div>
        </header>

        {view === "practice" ? (
          <>
            <section className="source-band" aria-label="练习歌曲">
              <div className="source-identity">
                <div className="source-art" aria-hidden="true">
                  <Music2 size={27} />
                </div>
                <div className="source-copy">
                  <span className="section-label">当前曲目</span>
                  <strong>{song?.name ?? "尚未载入音频"}</strong>
                  <span>
                    {song
                      ? `${formatTime(duration)} · ${song.isDemo ? "合成示例" : "本地文件"}`
                      : "支持 WAV、MP3、M4A、FLAC"}
                  </span>
                </div>
              </div>
              <div className="source-actions">
                <input
                  ref={fileInput}
                  type="file"
                  accept="audio/*"
                  hidden
                  disabled={sourceLocked}
                  onChange={onFileSelected}
                />
                <button className="button secondary" disabled={sourceLocked} onClick={loadDemo}>
                  <WandSparkles size={17} />
                  载入示例
                </button>
                <button
                  className="button primary"
                  disabled={sourceLocked}
                  onClick={() => fileInput.current?.click()}
                >
                  <Upload size={17} />
                  选择音频
                </button>
              </div>
            </section>

            {errorMessage && (
              <div className="error-banner" role="alert">
                <MicOff size={18} />
                <span>{errorMessage}</span>
                <button
                  className="icon-button"
                  title="关闭"
                  aria-label="关闭错误提示"
                  onClick={() => setErrorMessage(null)}
                >
                  <X size={17} />
                </button>
              </div>
            )}

            <section className="waveform-section" aria-label="音频波形与播放控制">
              <div className="section-heading compact-heading">
                <div>
                  <span className="section-label">练习区间</span>
                  <h2>波形与时间轴</h2>
                </div>
                <div className={`session-state ${sessionState}`}>
                  <span />
                  {status}
                </div>
              </div>
              <div
                className={`waveform-frame${song ? "" : " empty"}${sourceLocked ? " locked" : ""}`}
              >
                {song ? (
                  <>
                    <div ref={waveformElement} className="waveform" />
                    <div
                      className="selection-overlay"
                      style={{ left: `${overlayLeft}%`, width: `${overlayWidth}%` }}
                    />
                  </>
                ) : (
                  <div className="waveform-empty">
                    <FileAudio size={34} />
                    <strong>载入歌曲后显示波形</strong>
                    <span>可先使用合成示例完成一次预览评估</span>
                  </div>
                )}
              </div>
              <div className="transport-bar">
                <div className="transport-controls">
                  <button
                    className="transport-button"
                    title="回到区间起点"
                    aria-label="回到区间起点"
                    disabled={!song || sessionState === "recording"}
                    onClick={resetPlayback}
                  >
                    <RotateCcw size={18} />
                  </button>
                  <button
                    className="play-button"
                    title={isPlaying ? "暂停" : "播放"}
                    aria-label={isPlaying ? "暂停" : "播放"}
                    disabled={!song || sessionState === "recording"}
                    onClick={togglePlayback}
                  >
                    {isPlaying ? <Pause size={20} /> : <Play size={20} fill="currentColor" />}
                  </button>
                  <span className="time-readout">
                    {formatTime(currentTime)} <i>/</i> {formatTime(duration)}
                  </span>
                </div>
                <div className="range-fields">
                  <label>
                    起点
                    <input
                      type="number"
                      min={0}
                      max={Math.max(0, selectionEnd - 0.5)}
                      step={0.1}
                      value={selectionStart.toFixed(1)}
                      disabled={!song || sessionState === "recording"}
                      onChange={(event) => selectStart(Number(event.target.value))}
                    />
                  </label>
                  <span>—</span>
                  <label>
                    终点
                    <input
                      type="number"
                      min={selectionStart + 0.5}
                      max={duration}
                      step={0.1}
                      value={selectionEnd.toFixed(1)}
                      disabled={!song || sessionState === "recording"}
                      onChange={(event) => selectEnd(Number(event.target.value))}
                    />
                  </label>
                  <span className="range-duration">{selectedDuration.toFixed(1)} 秒</span>
                </div>
              </div>
              <div className="range-sliders">
                <input
                  aria-label="练习起点"
                  type="range"
                  min={0}
                  max={Math.max(duration, 0.5)}
                  step={0.1}
                  value={selectionStart}
                  disabled={!song || sessionState === "recording"}
                  onChange={(event) => selectStart(Number(event.target.value))}
                />
                <input
                  aria-label="练习终点"
                  type="range"
                  min={0.5}
                  max={Math.max(duration, 0.5)}
                  step={0.1}
                  value={selectionEnd}
                  disabled={!song || sessionState === "recording"}
                  onChange={(event) => selectEnd(Number(event.target.value))}
                />
              </div>
            </section>

            <section className="session-command-band" aria-label="录音与分析">
              <label className="rights-check">
                <input
                  type="checkbox"
                  checked={rightsAccepted}
                  disabled={!song || song.isDemo || sessionState === "recording"}
                  onChange={(event) => setRightsAccepted(event.target.checked)}
                />
                <span>我有权使用该音频进行个人练习</span>
              </label>
              <div className="session-actions">
                <button
                  className="button secondary"
                  disabled={sourceLocked}
                  onClick={runDemoAnalysis}
                >
                  <Sparkles size={17} />
                  运行示例评估
                </button>
                {sessionState === "recording" ? (
                  <button className="button danger" onClick={() => void stopSession()}>
                    <Square size={16} fill="currentColor" />
                    停止并分析
                  </button>
                ) : (
                  <button
                    className="button record"
                    disabled={
                      !song ||
                      !rightsAccepted ||
                      sessionState === "arming" ||
                      sessionState === "analyzing"
                    }
                    onClick={() => void startSession()}
                  >
                    <Mic size={17} />
                    {sessionState === "arming" ? "准备麦克风" : "开始练唱"}
                  </button>
                )}
              </div>
            </section>

            <section className="analysis-grid" aria-label="本地分析结果">
              <div className="corrections-panel">
                <div className="section-heading">
                  <div>
                    <span className="section-label">LOCAL PREVIEW</span>
                    <h2>纠错事件</h2>
                  </div>
                  {analysis && (
                    <span className="result-count">{analysis.corrections.length} 项</span>
                  )}
                </div>
                {analysis ? (
                  analysis.corrections.length > 0 ? (
                    <div className="correction-list">
                      {analysis.corrections.map((item, index) => (
                        <article className={`correction-row ${item.kind}`} key={item.id}>
                          <div className="correction-index">{String(index + 1).padStart(2, "0")}</div>
                          <div className="correction-copy">
                            <strong>{item.label}</strong>
                            <span>{item.detail}</span>
                          </div>
                          <div className="severity-track" title={`严重度 ${item.severity.toFixed(2)}`}>
                            <span style={{ width: `${Math.max(8, item.severity * 100)}%` }} />
                          </div>
                          <button
                            className="icon-button"
                            title="播放该区间"
                            aria-label={`播放 ${item.label} 区间`}
                            onClick={() => {
                              waveform.current?.setTime(selectionStart + item.startSeconds);
                              void waveform.current?.play();
                            }}
                          >
                            <Play size={16} />
                          </button>
                        </article>
                      ))}
                    </div>
                  ) : (
                    <div className="result-empty success">
                      <CheckCircle2 size={28} />
                      <strong>没有问题达到预览阈值</strong>
                    </div>
                  )
                ) : (
                  <div className="result-empty">
                    <Activity size={28} />
                    <strong>等待一次练唱</strong>
                    <span>评估结果会按时间区间列出</span>
                  </div>
                )}
              </div>

              <div className="coach-panel">
                <div className="section-heading">
                  <div>
                    <span className="section-label">COACH / RULE FALLBACK</span>
                    <h2>练习建议</h2>
                  </div>
                  <SlidersHorizontal size={19} />
                </div>
                {analysis ? (
                  <div className="coach-list">
                    {analysis.coachMessages.map((message, index) => (
                      <div className="coach-message" key={`${message}-${index}`}>
                        <span>{index + 1}</span>
                        <p>{message}</p>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="result-empty">
                    <Volume2 size={28} />
                    <strong>建议由结构化证据生成</strong>
                    <span>本地预览不会调用外部大模型</span>
                  </div>
                )}
              </div>

              <aside className="metrics-panel">
                <div className="section-heading">
                  <div>
                    <span className="section-label">MEASUREMENTS</span>
                    <h2>测量值</h2>
                  </div>
                  <Gauge size={19} />
                </div>
                <Metric
                  icon={<AudioLines size={17} />}
                  label="音高中心"
                  value={metricValue(analysis?.medianPitchCents, "音分")}
                />
                <Metric
                  icon={<Clock3 size={17} />}
                  label="起音偏差"
                  value={metricValue(analysis?.onsetOffsetMs, "毫秒")}
                />
                <Metric
                  icon={<Activity size={17} />}
                  label="有效覆盖"
                  value={analysis ? `${Math.round(analysis.voicedCoverage * 100)}%` : "—"}
                />
                <Metric
                  icon={<Gauge size={17} />}
                  label="证据置信"
                  value={analysis ? `${Math.round(analysis.confidence * 100)}%` : "—"}
                />
                <div className="evidence-actions">
                  <button
                    className="icon-text-button"
                    disabled={!lastCapture}
                    onClick={downloadCapture}
                  >
                    <Download size={16} />
                    录音 WAV
                  </button>
                  <button
                    className="icon-text-button"
                    disabled={!lastCapture}
                    onClick={downloadEvidence}
                  >
                    <Download size={16} />
                    时间证据
                  </button>
                </div>
              </aside>
            </section>
          </>
        ) : (
          <HistoryView entries={history} onBack={() => setView("practice")} />
        )}
      </main>

      <nav className="mobile-nav" aria-label="移动端导航">
        <button
          className={view === "practice" ? "active" : ""}
          onClick={() => setView("practice")}
        >
          <Mic size={20} />
          练唱
        </button>
        <button
          className={view === "history" ? "active" : ""}
          onClick={() => setView("history")}
        >
          <History size={20} />
          记录
        </button>
        <button onClick={openSettings}>
          <Settings2 size={20} />
          设置
        </button>
      </nav>

      {settingsOpen && (
        <div className="dialog-backdrop" role="presentation" onMouseDown={closeSettings}>
          <section
            className="settings-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="settings-title"
            onKeyDown={onSettingsKeyDown}
            onMouseDown={(event) => event.stopPropagation()}
          >
            <div className="dialog-header">
              <div>
                <span className="section-label">PREFERENCES</span>
                <h2 id="settings-title">偏好设置</h2>
              </div>
              <button
                ref={settingsCloseButton}
                className="icon-button"
                title="关闭"
                aria-label="关闭设置"
                onClick={closeSettings}
              >
                <X size={18} />
              </button>
            </div>
            <div className="setting-row">
              <div>
                <strong>分析模式</strong>
                <span>浏览器本地预览</span>
              </div>
              <span className="setting-value">LOCAL</span>
            </div>
            <div className="setting-row">
              <div>
                <strong>录音保留</strong>
                <span>仅保存在当前标签页内存</span>
              </div>
              <span className="setting-value">SESSION</span>
            </div>
            <div className="setting-row">
              <div>
                <strong>权威评分服务</strong>
                <span>等待服务器模型注册表配置</span>
              </div>
              <span className="setting-value muted">OFFLINE</span>
            </div>
          </section>
        </div>
      )}
    </div>
  );
}

function Metric({
  icon,
  label,
  value,
}: {
  icon: ReactNode;
  label: string;
  value: string;
}) {
  return (
    <div className="metric-row">
      <span className="metric-icon">{icon}</span>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function HistoryView({ entries, onBack }: { entries: HistoryEntry[]; onBack: () => void }) {
  return (
    <section className="history-view">
      <div className="history-summary">
        <div>
          <span className="section-label">SESSION HISTORY</span>
          <h2>当前标签页的练习记录</h2>
        </div>
        <button className="button secondary" onClick={onBack}>
          <Mic size={17} />
          返回练唱
        </button>
      </div>
      {entries.length === 0 ? (
        <div className="history-empty">
          <History size={34} />
          <strong>还没有练习记录</strong>
          <span>完成一次示例评估或麦克风录音后会显示在这里</span>
        </div>
      ) : (
        <div className="history-table" role="table" aria-label="练习记录">
          <div className="history-row header" role="row">
            <span role="columnheader">曲目</span>
            <span role="columnheader">时间</span>
            <span role="columnheader">覆盖率</span>
            <span role="columnheader">音高中心</span>
            <span role="columnheader">纠错</span>
          </div>
          {entries.map((entry) => (
            <div className="history-row" role="row" key={entry.id}>
              <strong role="cell">{entry.songName}</strong>
              <span role="cell" data-label="时间">
                {entry.createdAt.toLocaleTimeString("zh-CN", { hour12: false })}
              </span>
              <span role="cell" data-label="覆盖率">
                {Math.round(entry.analysis.voicedCoverage * 100)}%
              </span>
              <span role="cell" data-label="音高中心">
                {metricValue(entry.analysis.medianPitchCents, "音分")}
              </span>
              <span role="cell" data-label="纠错">
                {entry.analysis.corrections.length}
              </span>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function sessionStatus(state: SessionState): string {
  return {
    idle: "待机",
    arming: "请求麦克风",
    recording: "录音中",
    analyzing: "分析中",
    ready: "预览完成",
    error: "需要处理",
  }[state];
}

function metricValue(value: number | null | undefined, unit: string): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  const prefix = value > 0 ? "+" : "";
  return `${prefix}${Math.round(value)} ${unit}`;
}

function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}
