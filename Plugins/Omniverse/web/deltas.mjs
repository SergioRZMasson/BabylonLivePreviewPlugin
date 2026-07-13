// ===========================================================================
// Babylon Live Sync demo — scene-delta generator
// ===========================================================================
// Shared by the browser server (server.mjs) and the headless test
// (client-check.mjs). Produces protocol buffers with the TS CommandWriter — the
// same encoder a real producer (e.g. a USD/Omniverse bridge) would use.
import {
    CommandWriter,
    NodeKind,
    LightType,
} from "../../../Clients/ts/dist/babylon-live-sync.esm.js";

const GROUND_ID = 1;
const BOX_ID = 2;
const ORBIT_ID = 3;

function makeBox(half = 0.5) {
    const s = half;
    const positions = [
        -s, -s, -s, s, -s, -s, s, s, -s, -s, s, -s, // back
        -s, -s, s, s, -s, s, s, s, s, -s, s, s,      // front
    ];
    const indices = [
        0, 2, 1, 0, 3, 2, // back
        4, 5, 6, 4, 6, 7, // front
        0, 1, 5, 0, 5, 4, // bottom
        2, 3, 7, 2, 7, 6, // top
        1, 2, 6, 1, 6, 5, // right
        0, 4, 7, 0, 7, 3, // left
    ];
    return { positions, indices };
}

function makeGround(half = 4) {
    const s = half;
    const positions = [-s, 0, -s, s, 0, -s, s, 0, s, -s, 0, s];
    const indices = [0, 1, 2, 0, 2, 3];
    return { positions, indices };
}

/** Full initial scene: camera, lights, ground, two boxes. */
export function initialSnapshot() {
    const w = new CommandWriter();
    w.resetScene();
    w.setClearColor(0.05, 0.06, 0.09, 1.0);
    w.setCameraArcRotate(-Math.PI / 3, Math.PI / 3, 12, [0, 1, 0]);

    // A hemispheric fill + a directional key light.
    w.upsertLight(100, LightType.Hemispheric, [0.2, 1.0, 0.3], [1, 1, 1], 0.6);
    w.upsertLight(101, LightType.Directional, [-0.5, -1.0, -0.3], [1, 0.96, 0.9], 2.0);

    const ground = makeGround(5);
    w.upsertNode(GROUND_ID, 0, NodeKind.Mesh, "ground", [0, 0, 0], [0, 0, 0, 1], [1, 1, 1]);
    w.upsertMeshGeometry(GROUND_ID, ground.positions, null, null, ground.indices);
    w.upsertMaterial(GROUND_ID, [0.35, 0.37, 0.40, 1.0], 0.0, 0.9);

    const box = makeBox(0.8);
    w.upsertNode(BOX_ID, 0, NodeKind.Mesh, "box", [0, 1, 0], [0, 0, 0, 1], [1, 1, 1]);
    w.upsertMeshGeometry(BOX_ID, box.positions, null, null, box.indices);
    w.upsertMaterial(BOX_ID, [0.90, 0.35, 0.20, 1.0], 0.2, 0.4);

    const orbit = makeBox(0.4);
    w.upsertNode(ORBIT_ID, 0, NodeKind.Mesh, "orbit", [3, 1, 0], [0, 0, 0, 1], [1, 1, 1]);
    w.upsertMeshGeometry(ORBIT_ID, orbit.positions, null, null, orbit.indices);
    w.upsertMaterial(ORBIT_ID, [0.15, 0.55, 0.85, 1.0], 0.9, 0.25);

    return w.finish();
}

/**
 * One animation frame at time `t` (seconds): spin the centre box, orbit the
 * small box around it, and gently recolour the centre box.
 */
export function animationFrame(t) {
    const w = new CommandWriter();

    // Centre box: spin about Y.
    const half = t * 0.8;
    w.setTransform(2, [0, 1, 0], [0, Math.sin(half), 0, Math.cos(half)], [1, 1, 1]);

    // Small box: orbit the centre box in the XZ plane.
    const r = 3.0;
    w.setTransform(3, [Math.cos(t) * r, 1, Math.sin(t) * r], [0, 0, 0, 1], [1, 1, 1]);

    // Centre box colour pulses between orange and magenta.
    const k = 0.5 + 0.5 * Math.sin(t * 0.7);
    w.upsertMaterial(2, [0.9, 0.35 * (1 - k) + 0.1 * k, 0.2 + 0.6 * k, 1.0], 0.2, 0.4);

    return w.finish();
}
