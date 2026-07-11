import { existsSync, readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

import {
  classifyMgg,
  isMggFilename,
  mggIssueMessage,
  normalizePlainMgg,
} from "./mgg";

const REAL_FIXTURE = process.env.MUSIC_AI_MGG_FIXTURE;

describe("MGG intake", () => {
  it("classifies MusicEx containers without reading the complete file", async () => {
    const footer = musicExFooter("fixture-track.mgg");
    const encrypted = new File(
      [blobPart(new Uint8Array(8_192)), blobPart(footer)],
      "fixture.mgg",
    );

    const result = await classifyMgg(encrypted);

    expect(result).toEqual({ type: "key_unavailable", mediaName: "fixture-track.mgg" });
    if (result.type !== "plain_ogg") {
      expect(mggIssueMessage(result)).toContain("不会读取账号或设备密钥");
      expect(mggIssueMessage(result)).toContain("macOS 本机转换器");
    }
  });

  it("normalizes a genuinely plain Ogg file with an MGG extension", async () => {
    const file = new File(
      [blobPart(ascii("OggS")), blobPart(new Uint8Array(128))],
      "plain.mgg",
      {
        type: "",
        lastModified: 123,
      },
    );

    expect(await classifyMgg(file)).toEqual({ type: "plain_ogg" });
    const normalized = normalizePlainMgg(file);
    expect(normalized.name).toBe("plain.ogg");
    expect(normalized.type).toBe("audio/ogg");
    expect(normalized.lastModified).toBe(123);
  });

  it("rejects legacy and opaque encrypted MGG variants", async () => {
    const qtag = new File(
      [blobPart(new Uint8Array(64)), blobPart(ascii("QTag"))],
      "legacy.mgg",
    );
    const opaque = new File([blobPart(new Uint8Array([1, 2, 3, 4]))], "opaque.mgg1");

    expect(await classifyMgg(qtag)).toEqual({ type: "encrypted_unsupported" });
    expect(await classifyMgg(opaque)).toEqual({ type: "encrypted_unsupported" });
    expect(isMggFilename("TRACK.MGGL")).toBe(true);
    expect(isMggFilename("track.ogg")).toBe(false);
  });

  it.skipIf(!REAL_FIXTURE || !existsSync(REAL_FIXTURE))(
    "classifies the external MusicEx sample",
    async () => {
      const bytes = readFileSync(REAL_FIXTURE as string);
      const file = new File([blobPart(bytes)], "external.mgg");

      const result = await classifyMgg(file);

      expect(result).toEqual({
        type: "key_unavailable",
        mediaName: "O4M0002AIxAT3HZwiA.mgg",
      });
    },
  );
});

function musicExFooter(mediaName: string): Uint8Array {
  const footer = new Uint8Array(192);
  const nameOffset = 72;
  for (let index = 0; index < mediaName.length; index += 1) {
    footer[nameOffset + index * 2] = mediaName.charCodeAt(index);
  }
  const view = new DataView(footer.buffer);
  view.setUint32(footer.length - 16, footer.length, true);
  view.setUint32(footer.length - 12, 1, true);
  footer.set(ascii("musicex\0"), footer.length - 8);
  return footer;
}

function ascii(value: string): Uint8Array {
  return new TextEncoder().encode(value);
}

function blobPart(value: Uint8Array): ArrayBuffer {
  const buffer = new ArrayBuffer(value.byteLength);
  new Uint8Array(buffer).set(value);
  return buffer;
}
