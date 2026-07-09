// ===========================================================================
// Babylon Live Sync — browser / web public API
// ===========================================================================
// Add this to a Babylon.js web app, point it at a source, and the scene is kept
// live from scene-delta buffers:
//
//   import { BabylonLiveSync } from "@babylonjs/live-sync";
//   const sync = new BabylonLiveSync(scene, { source: "ws://host:8765" });
//   await sync.start();
//
// The host owns the engine, scene and render loop; this class only decodes
// deltas and applies them (via SceneApplier) over a transport (Source).
import type * as BJS from "babylonjs";
import { Babylon } from "./babylon";
import { SceneApplier } from "./SceneApplier";
import { Source } from "./transports/Source";
import { WebSocketSource } from "./transports/WebSocketSource";

export interface BabylonLiveSyncOptions {
    /** A WebSocket URL (ws://…/wss://…) or a custom Source implementation. */
    source: string | Source;
    /** Babylon namespace, if not using the global BABYLON. */
    babylon?: Babylon;
    /** Default environment (.env) bytes to apply as IBL (optional). */
    environmentBuffer?: Uint8Array | null;
    /** Apply the standard image-processing config (default true). */
    imageProcessing?: boolean;
}

export class BabylonLiveSync {
    private readonly applier: SceneApplier;
    private readonly source: Source;
    private started = false;

    constructor(scene: BJS.Scene, options: BabylonLiveSyncOptions) {
        this.applier = new SceneApplier({
            babylon: options.babylon,
            environmentBuffer: options.environmentBuffer ?? null,
            imageProcessing: options.imageProcessing,
        });
        this.applier.setScene(scene);
        this.source = typeof options.source === "string"
            ? new WebSocketSource(options.source)
            : options.source;
    }

    /** Connect the source and begin applying deltas. */
    async start(): Promise<void> {
        if (this.started) {
            return;
        }
        this.started = true;
        await this.source.start((buffer) => this.applier.apply(buffer));
    }

    /** Disconnect the source. */
    stop(): void {
        if (!this.started) {
            return;
        }
        this.started = false;
        this.source.stop();
    }

    /** The underlying applier (advanced use). */
    getApplier(): SceneApplier {
        return this.applier;
    }
}
