// ===========================================================================
// Babylon Live Sync — bundle build (esbuild)
// ===========================================================================
// Usage:
//   node build.mjs --entry native [--dcc maya] [--out <path>]
//       Build the Babylon Native bundle (IIFE) that a DCC plugin ships as its
//       live_preview.js. --dcc is embedded as the BLP_DCC define.
//   node build.mjs --web
//       Build the browser/npm bundles (ESM + UMD) into dist/.
//
// Babylon is never bundled: the library uses the host's global BABYLON (only
// `import type` references babylonjs, which esbuild erases).
import esbuild from "esbuild";
import { parseArgs } from "node:util";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { mkdirSync } from "node:fs";

const here = dirname(fileURLToPath(import.meta.url));
const srcDir = resolve(here, "src");
const distDir = resolve(here, "dist");

const { values } = parseArgs({
    options: {
        entry: { type: "string", default: "native" },
        dcc: { type: "string", default: "native" },
        out: { type: "string" },
        web: { type: "boolean", default: false },
    },
});

const shared = {
    bundle: true,
    platform: "browser",
    target: "es2018",
    legalComments: "none",
    logLevel: "info",
};

async function buildNative() {
    const out = values.out ? resolve(values.out) : resolve(distDir, "live_preview.js");
    mkdirSync(dirname(out), { recursive: true });
    await esbuild.build({
        ...shared,
        entryPoints: [resolve(srcDir, "entries/native.ts")],
        format: "iife",
        outfile: out,
        define: { BLP_DCC: JSON.stringify(values.dcc) },
        banner: { js: "// Babylon Live Sync — generated bundle. Do not edit; edit Clients/ts/src." },
    });
    console.log(`[build] native bundle (dcc=${values.dcc}) -> ${out}`);
}

async function buildWeb() {
    mkdirSync(distDir, { recursive: true });
    await esbuild.build({
        ...shared,
        entryPoints: [resolve(srcDir, "entries/web.ts")],
        format: "esm",
        outfile: resolve(distDir, "babylon-live-sync.esm.js"),
    });
    await esbuild.build({
        ...shared,
        entryPoints: [resolve(srcDir, "entries/web.ts")],
        format: "iife",
        globalName: "BabylonLiveSync",
        outfile: resolve(distDir, "babylon-live-sync.umd.js"),
    });
    console.log(`[build] web bundles -> ${distDir}`);
}

try {
    if (values.web) {
        await buildWeb();
    } else {
        await buildNative();
    }
} catch (err) {
    console.error(err);
    process.exit(1);
}
