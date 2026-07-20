// ===========================================================================
// Babylon Live Sync — Babylon Native host (DCC plugins)
// ===========================================================================
// The in-process host for Babylon Native (Blender / Maya / 3ds Max plugins).
// Owns the NativeEngine, the current scene, the render loop, and the readback-
// ready notification, and exposes the C++ bridge globals (applyCommands,
// blpEval). This is the TypeScript port of Shared/Scripts/live_preview.js's
// top-level; the per-DCC native entry just instantiates it.
import type * as BJS from "babylonjs";
import { getGlobalBabylon } from "./babylon";
import { SceneApplier } from "./SceneApplier";

// The C++ core registers these globals before the script runs.
declare const _blpGetEnvironmentBytes: (() => ArrayBuffer) | undefined;
declare const _blpNotifyReady: (() => void) | undefined;

export class NativeHost {
    readonly engine: BJS.NativeEngine;
    readonly applier: SceneApplier;
    private notifiedReady = false;

    constructor() {
        const B = getGlobalBabylon();
        this.engine = new B.NativeEngine();

        // Babylon expects a rendering canvas; the Window polyfill stands in.
        const win = (globalThis as unknown as { window: unknown }).window;
        this.engine.getRenderingCanvas = () => win as never;
        (this.engine as unknown as { getInputElement: () => unknown }).getInputElement = () => 0;

        this.applier = new SceneApplier({
            babylon: B,
            onResetScene: () => this.createScene(),
        });
        this.applier.setScene(this.createDefaultScene());
        this.loadEnvironment();

        // Expose the C++ bridge globals.
        const g = globalThis as unknown as Record<string, unknown>;
        g.applyCommands = (buffer: ArrayBuffer) => this.applier.apply(buffer);
        g.blpEval = (code: string) => this.blpEval(code);

        this.engine.runRenderLoop(() => this.renderFrame());
        console.log("[live_sync] native host ready, Babylon " + B.Engine.Version);
    }

    /** Bare scene + arc camera, used on ResetScene (disposes the previous one). */
    private createScene(): BJS.Scene {
        const B = getGlobalBabylon();
        const old = this.applier.getScene();
        if (old) {
            old.dispose();
            (this.engine as unknown as { releaseEffects?: () => void }).releaseEffects?.();
        }
        const scene = new B.Scene(this.engine);
        const cam = new B.ArcRotateCamera(
            "camera", -Math.PI / 2, Math.PI / 3, 10, B.Vector3.Zero(), scene);
        scene.activeCamera = cam;
        return scene;
    }

    /** The startup scene: a PBR sphere on a ground, so there's something to see. */
    private createDefaultScene(): BJS.Scene {
        const B = getGlobalBabylon();
        const scene = new B.Scene(this.engine);
        // Classic Babylon.js clear color (dark purple-blue) — marks this as a Babylon scene.
        scene.clearColor = new B.Color4(0.2, 0.2, 0.3, 1.0);

        const camera = new B.ArcRotateCamera(
            "camera", -Math.PI / 3, Math.PI / 3, 8, B.Vector3.Zero(), scene);
        scene.activeCamera = camera;

        const light = new B.HemisphericLight("light", new B.Vector3(0.3, 1.0, 0.2), scene);
        light.intensity = 0.9;

        const mat = new B.PBRMetallicRoughnessMaterial("mat", scene);
        mat.baseColor = new B.Color3(0.90, 0.35, 0.20);
        mat.metallic = 0.1;
        mat.roughness = 0.5;

        const sphere = B.MeshBuilder.CreateSphere("sphere", { diameter: 2, segments: 32 }, scene);
        sphere.position.y = 1;
        sphere.material = mat;

        const ground = B.MeshBuilder.CreateGround("ground", { width: 8, height: 8 }, scene);
        const gmat = new B.PBRMetallicRoughnessMaterial("groundMat", scene);
        gmat.baseColor = new B.Color3(0.35, 0.37, 0.40);
        gmat.metallic = 0.0;
        gmat.roughness = 0.9;
        ground.material = gmat;

        return scene;
    }

    /** Pull the default .env bytes from the core (registered before this runs). */
    private loadEnvironment(): void {
        if (typeof _blpGetEnvironmentBytes !== "function") {
            return;
        }
        try {
            const ab = _blpGetEnvironmentBytes();
            if (ab && ab.byteLength > 0) {
                this.applier.setEnvironmentBuffer(new Uint8Array(ab));
                console.log("[live_sync] environment loaded (" + ab.byteLength + " bytes)");
            }
        } catch (e) {
            console.error("[live_sync] environment pull failed: " + e);
        }
    }

    private renderFrame(): void {
        const scene = this.applier.getScene();
        if (scene && scene.activeCamera) {
            scene.render();
            if (!this.notifiedReady) {
                this.notifiedReady = true;
                console.log("[live_sync] first frame rendered");
                if (typeof _blpNotifyReady === "function") {
                    _blpNotifyReady();
                }
            }
        }
    }

    private blpEval(code: string): unknown {
        // Expose the same names the hand-written live_preview.js did, so debug
        // evals (and the Python test harnesses) can reference `currentScene`,
        // `engine` and `applier`. Direct eval captures this lexical scope; the
        // bundle is not minified, so these names are preserved.
        const currentScene = this.applier.getScene();
        const engine = this.engine;
        const applier = this.applier;
        void currentScene; void engine; void applier;
        try {
            // eslint-disable-next-line no-eval
            return eval(code);
        } catch (e) {
            console.error("[live_sync] blpEval error: " + e);
            return null;
        }
    }
}
