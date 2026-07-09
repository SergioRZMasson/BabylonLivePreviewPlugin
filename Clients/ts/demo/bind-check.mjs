// ===========================================================================
// Babylon Live Sync — path-addressing (BindNodePath) validation
// ===========================================================================
// Simulates a pre-loaded (glTF-baked) node by creating a named mesh, then binds
// it by path and drives it with id-addressed deltas — the "bake once, update
// often" flow, without needing a real glTF loader in Node.
//
//   node Clients/ts/demo/bind-check.mjs
import { createRequire } from "node:module";
import {
    SceneApplier,
    CommandWriter,
    NodeKind,
} from "../dist/babylon-live-sync.esm.js";

const require = createRequire(import.meta.url);
const BABYLON = require("babylonjs");

function main() {
    let failures = 0;
    const check = (cond, msg) => {
        if (!cond) { console.log("  FAIL: " + msg); failures++; }
        else { console.log("  ok:   " + msg); }
    };

    const engine = new BABYLON.NullEngine();
    const scene = new BABYLON.Scene(engine);

    // Simulate an asset loaded by the host: a mesh named by its stable path, plus
    // another node carrying the path in glTF-style metadata.extras.usdPath.
    const byName = new BABYLON.Mesh("/World/Cube", scene);
    const byExtras = new BABYLON.TransformNode("sanitized_name", scene);
    byExtras.metadata = { gltf: { extras: { usdPath: "/World/Lamp" } } };

    const applier = new SceneApplier({ babylon: BABYLON });
    applier.setScene(scene);

    // Bind both by path, then drive them by id.
    const w = new CommandWriter();
    w.bindNodePath(10, "/World/Cube");
    w.bindNodePath(11, "/World/Lamp");
    w.setTransform(10, [1, 2, 3], [0, 0, 0, 1], [2, 2, 2]);
    w.setTransform(11, [4, 5, 6], [0, 0, 0, 1], [1, 1, 1]);
    applier.apply(w.finish());

    check(Math.abs(byName.position.x - 1) < 1e-5 &&
          Math.abs(byName.position.y - 2) < 1e-5 &&
          Math.abs(byName.position.z - 3) < 1e-5,
          "node bound by name moved to (1,2,3): " + byName.position.toString());
    check(Math.abs(byName.scaling.x - 2) < 1e-5, "node bound by name scaled to 2");
    check(Math.abs(byExtras.position.x - 4) < 1e-5 &&
          Math.abs(byExtras.position.z - 6) < 1e-5,
          "node bound by extras.usdPath moved to (4,5,6): " + byExtras.position.toString());

    // Binding an unknown path is a safe no-op (does not throw / create nodes).
    const before = scene.meshes.length + scene.transformNodes.length;
    const w2 = new CommandWriter();
    w2.bindNodePath(12, "/does/not/exist");
    w2.setTransform(12, [9, 9, 9], [0, 0, 0, 1], [1, 1, 1]);
    applier.apply(w2.finish());
    check(scene.meshes.length + scene.transformNodes.length === before,
          "binding an unknown path creates nothing");

    // A base value used just to keep NodeKind referenced (protocol import sanity).
    check(NodeKind.Mesh === 1, "NodeKind import sane");

    scene.dispose();
    engine.dispose();

    if (failures === 0) {
        console.log("[bind-check] ALL PASS");
        process.exit(0);
    }
    console.log("[bind-check] " + failures + " FAILURE(S)");
    process.exit(1);
}

main();
