// ===========================================================================
// Babylon Live Sync demo — headless end-to-end validation
// ===========================================================================
// Proves the full WebSocket path with no browser: starts a ws server that emits
// the same deltas as the demo, then drives a headless Babylon NullEngine scene
// through BabylonLiveSync and asserts the scene was built and is animating.
//
//   node Clients/ts/demo/client-check.mjs
import { createRequire } from "node:module";
import { WebSocketServer } from "ws";
import { initialSnapshot, animationFrame } from "./deltas.mjs";
import { BabylonLiveSync } from "../dist/babylon-live-sync.esm.js";

const require = createRequire(import.meta.url);
const BABYLON = require("babylonjs");

const PORT = 8770;

function startServer() {
    const wss = new WebSocketServer({ port: PORT });
    wss.on("connection", (ws) => {
        ws.binaryType = "arraybuffer";
        ws.send(initialSnapshot());
        const start = Date.now();
        const timer = setInterval(() => {
            if (ws.readyState === ws.OPEN) {
                ws.send(animationFrame((Date.now() - start) / 1000));
            }
        }, 33);
        ws.on("close", () => clearInterval(timer));
    });
    return wss;
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function main() {
    let failures = 0;
    const check = (cond, msg) => {
        if (!cond) { console.log("  FAIL: " + msg); failures++; }
        else { console.log("  ok:   " + msg); }
    };

    if (typeof globalThis.WebSocket !== "function") {
        console.log("[check] FAIL: no global WebSocket (need Node >= 22)");
        process.exit(2);
    }

    const wss = startServer();

    const engine = new BABYLON.NullEngine({
        renderWidth: 512, renderHeight: 512, textureSize: 512,
        deterministicLockstep: false, lockstepMaxSteps: 1,
    });
    const scene = new BABYLON.Scene(engine);

    const sync = new BabylonLiveSync(scene, {
        source: "ws://localhost:" + PORT,
        babylon: BABYLON,
    });
    await sync.start();

    // Let the initial snapshot + a few animation frames arrive.
    await sleep(700);

    console.log("[check] scene after initial snapshot:");
    check(scene.meshes.length >= 3, "meshes created (ground+box+orbit): " + scene.meshes.length);
    check(!!scene.getMeshByName("ground"), "ground mesh present");
    check(!!scene.getMeshByName("box"), "box mesh present");
    check(!!scene.getMeshByName("orbit"), "orbit mesh present");
    check(!!scene.activeCamera && scene.activeCamera.getClassName() === "ArcRotateCamera", "arc-rotate camera set");
    check(scene.lights.length >= 2, "lights created: " + scene.lights.length);

    const orbit = scene.getMeshByName("orbit");
    const box = scene.getMeshByName("box");
    const mat = box && box.material;
    check(!!mat && mat.getClassName() === "PBRMetallicRoughnessMaterial", "box uses PBR material");

    // Verify animation: the orbit box position and the box rotation must change.
    const p0 = orbit ? orbit.position.clone() : null;
    const q0 = box && box.rotationQuaternion ? box.rotationQuaternion.clone() : null;
    await sleep(500);
    const p1 = orbit ? orbit.position.clone() : null;
    const q1 = box && box.rotationQuaternion ? box.rotationQuaternion.clone() : null;

    check(!!p0 && !!p1 && (Math.abs(p0.x - p1.x) + Math.abs(p0.z - p1.z)) > 0.05,
        "orbit box position animates (dx+dz=" +
        (p0 && p1 ? (Math.abs(p0.x - p1.x) + Math.abs(p0.z - p1.z)).toFixed(3) : "?") + ")");
    check(!!q0 && !!q1 && (Math.abs(q0.y - q1.y) > 0.001),
        "centre box rotation animates");

    sync.stop();
    scene.dispose();
    engine.dispose();
    await new Promise((r) => wss.close(r));

    if (failures === 0) {
        console.log("[check] ALL PASS");
        process.exit(0);
    }
    console.log("[check] " + failures + " FAILURE(S)");
    process.exit(1);
}

main().catch((e) => { console.error(e); process.exit(1); });
