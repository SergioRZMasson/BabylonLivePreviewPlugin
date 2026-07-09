// ===========================================================================
// Babylon Live Sync — native (in-process) transport
// ===========================================================================
// For Babylon Native hosts (DCC plugins), the C++ side hands scene-delta buffers
// to JS by calling a global function. NativeSource installs that global and
// forwards buffers to the SceneApplier, so the native path fits the same Source
// abstraction as WebSocket.
import { Source } from "./Source";

export interface NativeSourceOptions {
    /** Name of the global function the host calls (default "applyCommands"). */
    globalName?: string;
}

export class NativeSource implements Source {
    private readonly globalName: string;
    private installed = false;

    constructor(options: NativeSourceOptions = {}) {
        this.globalName = options.globalName ?? "applyCommands";
    }

    start(onMessage: (buffer: ArrayBuffer) => void): void {
        const g = globalThis as unknown as Record<string, unknown>;
        g[this.globalName] = (buffer: ArrayBuffer) => onMessage(buffer);
        this.installed = true;
    }

    stop(): void {
        if (this.installed) {
            const g = globalThis as unknown as Record<string, unknown>;
            delete g[this.globalName];
            this.installed = false;
        }
    }
}
