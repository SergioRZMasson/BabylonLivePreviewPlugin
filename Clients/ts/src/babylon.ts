// ===========================================================================
// Babylon Live Sync — access to the BABYLON namespace
// ===========================================================================
// The library never bundles Babylon. It uses the BABYLON namespace provided by
// the host: the global `BABYLON` (Babylon Native, or a UMD <script> in the
// browser), or an explicitly injected namespace (e.g. `import * as BABYLON from
// "@babylonjs/core"` passed via options). `import type` is erased at build time,
// so no Babylon code ends up in the bundle.
import type * as BJS from "babylonjs";

export type Babylon = typeof BJS;

export function getGlobalBabylon(): Babylon {
    const b = (globalThis as unknown as { BABYLON?: Babylon }).BABYLON;
    if (!b) {
        throw new Error(
            "[live_sync] global BABYLON not found. Load babylon.js first, " +
            "or pass options.babylon with your Babylon namespace.");
    }
    return b;
}
