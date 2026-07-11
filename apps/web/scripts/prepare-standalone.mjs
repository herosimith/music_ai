import { cp, mkdir, rm } from "node:fs/promises";
import path from "node:path";

const appRoot = process.cwd();
const standaloneRoot = path.join(appRoot, ".next", "standalone", "apps", "web");

await mkdir(path.join(standaloneRoot, ".next"), { recursive: true });
await replaceDirectory(
  path.join(appRoot, ".next", "static"),
  path.join(standaloneRoot, ".next", "static"),
);
await replaceDirectory(path.join(appRoot, "public"), path.join(standaloneRoot, "public"));

async function replaceDirectory(source, destination) {
  await rm(destination, { recursive: true, force: true });
  await cp(source, destination, { recursive: true });
}
