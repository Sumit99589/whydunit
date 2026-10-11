import { build } from "esbuild";

const common = { entryPoints: ["src/index.ts"], bundle: true, minify: true, target: "es2019", sourcemap: true };
// IIFE for a <script> tag: exposes window.whydunit
await build({ ...common, format: "iife", globalName: "whydunit", outfile: "dist/whydunit.js" });
await build({ ...common, format: "esm", outfile: "dist/whydunit.esm.js" });
// The recorder is its own file, loaded on demand by sampled sessions.
await build({ ...common, entryPoints: ["src/recorder.ts"], format: "iife", outfile: "dist/whydunit-record.js" });
console.log("built dist/whydunit.js, dist/whydunit.esm.js and dist/whydunit-record.js");
