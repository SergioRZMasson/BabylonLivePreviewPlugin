// ===========================================================================
// USD bridge — end-to-end verifier (USD -> WebSocket -> Babylon)
// ===========================================================================
// Connects a headless Babylon NullEngine scene to a running USD bridge via
// BabylonLiveSync and asserts the USD stage was translated into a live scene.
//
//   python Plugins/Omniverse/usd-bridge/bridge.py --stage Plugins/Omniverse/usd-bridge/sample.usda --port 8765 &
//   node Plugins/Omniverse/usd-bridge/verify.mjs 8765
import { createRequire } from "node:module";
import { BabylonLiveSync } from "../../../Clients/ts/dist/babylon-live-sync.esm.js";

const require = createRequire(import.meta.url);
const BABYLON = require("babylonjs");

const port = Number(process.argv[2] || 8765);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function main() {
    let failures = 0;
    const check = (cond, msg) => {
        if (!cond) { console.log("  FAIL: " + msg); failures++; }
        else { console.log("  ok:   " + msg); }
    };

    const engine = new BABYLON.NullEngine({
        renderWidth: 512, renderHeight: 512, textureSize: 512,
        deterministicLockstep: false, lockstepMaxSteps: 1,
    });
    const scene = new BABYLON.Scene(engine);

    const sync = new BabylonLiveSync(scene, {
        source: "ws://localhost:" + port,
        babylon: BABYLON,
    });
    await sync.start();
    await sleep(800);

    console.log("[usd-verify] scene from the USD bridge:");
    check(!!scene.getMeshByName("Cube"), "Cube mesh present");
    check(!!scene.getMeshByName("Ground"), "Ground mesh present");
    check(!!scene.activeCamera && scene.activeCamera.getClassName() === "ArcRotateCamera",
        "arc-rotate camera set");
    check(scene.lights.length >= 1, "light(s) created: " + scene.lights.length);

    const cube = scene.getMeshByName("Cube");
    check(!!cube && Math.abs(cube.position.y - 1.0) < 1e-3, "Cube at y=1 (USD Y-up preserved)");
    check(!!cube && cube.getTotalVertices() === 8, "Cube has 8 vertices");

    sync.stop();
    scene.dispose();
    engine.dispose();

    if (failures === 0) {
        console.log("[usd-verify] ALL PASS");
        process.exit(0);
    }
    console.log("[usd-verify] " + failures + " FAILURE(S)");
    process.exit(1);
}

main().catch((e) => { console.error(e); process.exit(1); });
