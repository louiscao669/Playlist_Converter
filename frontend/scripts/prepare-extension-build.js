const fs = require("fs");
const path = require("path");

const projectRoot = path.resolve(__dirname, "..");
const webBuildDir = path.join(projectRoot, "build");
const extensionBuildDir = path.join(projectRoot, "build-extension");
const extensionManifest = path.join(webBuildDir, "extension", "manifest.json");

if (!fs.existsSync(webBuildDir)) {
  throw new Error("Run react-scripts build before preparing the extension build.");
}

if (!fs.existsSync(extensionManifest)) {
  throw new Error(`Missing extension manifest at ${extensionManifest}`);
}

fs.rmSync(extensionBuildDir, { recursive: true, force: true });
fs.cpSync(webBuildDir, extensionBuildDir, { recursive: true });
fs.copyFileSync(extensionManifest, path.join(extensionBuildDir, "manifest.json"));

console.log(`Extension build ready at ${path.relative(projectRoot, extensionBuildDir)}`);
