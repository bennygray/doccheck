/**
 * e2e 种子数据脚本 - C1 infra-base 阶段为占位
 *
 * C1 无业务数据需要种入;保留此文件以便后续 C3 project-mgmt / C4 file-upload 直接扩展。
 * 运行方式:`npm run seed`(在项目根)
 */

async function main() {
  console.log("[seed] C1 infra-base: 无业务数据需要种入,跳过。");
  console.log("[seed] 后续 change 可在此注册种子数据(项目/投标人/文件等)。");
}

main().catch((err) => {
  console.error("[seed] failed:", err);
  process.exit(1);
});
