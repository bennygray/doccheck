/**
 * E2E 用压缩包 fixture (C4 file-upload §12.1)。
 *
 * Node-side 写一个真实小 ZIP 到 tmp 目录,Playwright `setInputFiles` 上传。
 * 内容:2 个 docx + 1 个 jpg(纯字节 stub,不要求合法 OOXML)。
 *
 * 加密 7z fixture 没法在纯 Node 端便捷生成(py7zr 是 Python),所以加密场景的
 * spec 改用预置二进制 fixture;仓库内不带,需手动用 backend 端 fixture 生成
 * 后放进 e2e/fixtures/encrypted-sample.7z。详见 c4-encrypted-archive.spec.ts。
 */
import AdmZip from "adm-zip";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

export function createNormalZip(): string {
  const dir = mkdtempSync(join(tmpdir(), "c4-l3-"));
  const out = join(dir, "bid.zip");

  const zip = new AdmZip();
  zip.addFile("contract.docx", Buffer.from("PK\x03\x04dummy-docx"));
  zip.addFile("dir/quote.xlsx", Buffer.from("PK\x03\x04dummy-xlsx"));
  zip.addFile("dir/photo.jpg", Buffer.from("\xff\xd8\xff\xe0jpeg-stub"));
  zip.writeZip(out);
  return out;
}

/**
 * 写一个最小合法 ZIP(no encryption);若需要加密 fixture,放置一个预制 7z
 * 在 ``e2e/fixtures/encrypted-sample.7z`` 路径,c4-encrypted-archive.spec.ts
 * 检测到才跑加密分支,否则 skip。
 */
export function createMinimalZipFor(path: string): void {
  const zip = new AdmZip();
  zip.addFile("a.docx", Buffer.from("PK\x03\x04docx"));
  zip.writeZip(path);
}

export const ENCRYPTED_FIXTURE_PATH = join(
  __dirname,
  "encrypted-sample.7z",
);
export const ENCRYPTED_FIXTURE_PASSWORD = "secret";

// 写入辅助:测试可以临时往 fixture 目录放 ZIP / 7z 文件
export function writeBytes(path: string, data: Buffer): void {
  writeFileSync(path, data);
}
