export type MggClassification =
  | { type: "plain_ogg" }
  | { type: "key_unavailable"; mediaName: string | null }
  | { type: "encrypted_unsupported" };

const MUSICEX_MAGIC = new Uint8Array([0x6d, 0x75, 0x73, 0x69, 0x63, 0x65, 0x78, 0x00]);
const OGG_MAGIC = new Uint8Array([0x4f, 0x67, 0x67, 0x53]);
const TAIL_BYTES = 4_096;

export function isMggFilename(name: string): boolean {
  return /\.mgg(?:0|1|l)?$/i.test(name);
}

export async function classifyMgg(file: Blob): Promise<MggClassification> {
  const [headerBuffer, tailBuffer] = await Promise.all([
    file.slice(0, 16).arrayBuffer(),
    file.slice(Math.max(0, file.size - TAIL_BYTES)).arrayBuffer(),
  ]);
  const header = new Uint8Array(headerBuffer);
  const tail = new Uint8Array(tailBuffer);

  if (endsWith(tail, MUSICEX_MAGIC)) {
    return { type: "key_unavailable", mediaName: musicExMediaName(tail) };
  }
  if (endsWithAscii(tail, "QTag") || endsWithAscii(tail, "STag")) {
    return { type: "encrypted_unsupported" };
  }
  if (startsWith(header, OGG_MAGIC)) return { type: "plain_ogg" };
  return { type: "encrypted_unsupported" };
}

export function normalizePlainMgg(file: File): File {
  const name = file.name.replace(/\.mgg(?:0|1|l)?$/i, ".ogg");
  return new File([file], name, {
    type: "audio/ogg",
    lastModified: file.lastModified,
  });
}

export function mggIssueMessage(classification: Exclude<MggClassification, { type: "plain_ogg" }>): string {
  if (classification.type === "key_unavailable") {
    return (
      "MGG 密钥不可用：该文件是 MusicEx 加密容器，本应用不会读取账号或设备密钥。" +
      "请在你有权使用的音乐客户端中导出 WAV、FLAC 或 MP3 后重新选择。"
    );
  }
  return "该 MGG 文件包含不支持的加密音频。请从授权客户端导出 WAV、FLAC 或 MP3 后重新选择。";
}

function musicExMediaName(tail: Uint8Array): string | null {
  if (tail.length < 16) return null;
  const footerSize = new DataView(
    tail.buffer,
    tail.byteOffset + tail.length - 16,
    4,
  ).getUint32(0, true);
  if (footerSize < 32 || footerSize > tail.length) return null;
  const footer = tail.subarray(tail.length - footerSize);
  const candidates: string[] = [];
  for (let alignment = 0; alignment < 2; alignment += 1) {
    let current = "";
    for (let offset = alignment; offset + 1 < footer.length - 16; offset += 2) {
      const code = footer[offset] | (footer[offset + 1] << 8);
      if (code >= 0x20 && code <= 0x7e) {
        current += String.fromCharCode(code);
      } else {
        if (/\.mgg(?:0|1|l)?$/i.test(current)) candidates.push(current);
        current = "";
      }
    }
    if (/\.mgg(?:0|1|l)?$/i.test(current)) candidates.push(current);
  }
  return candidates.sort((left, right) => right.length - left.length)[0] ?? null;
}

function startsWith(value: Uint8Array, prefix: Uint8Array): boolean {
  return prefix.every((byte, index) => value[index] === byte);
}

function endsWith(value: Uint8Array, suffix: Uint8Array): boolean {
  if (value.length < suffix.length) return false;
  const start = value.length - suffix.length;
  return suffix.every((byte, index) => value[start + index] === byte);
}

function endsWithAscii(value: Uint8Array, suffix: string): boolean {
  return endsWith(value, new TextEncoder().encode(suffix));
}
