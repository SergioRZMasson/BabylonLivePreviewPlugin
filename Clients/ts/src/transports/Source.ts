// ===========================================================================
// Babylon Live Sync — transport source interface
// ===========================================================================
// A Source delivers scene-delta buffers to a SceneApplier, regardless of origin
// (native function call, WebSocket, file, ...). The consumer wires
// source.start(applier.apply).

export interface Source {
    /** Begin delivering buffers. `onMessage` is called per delta. */
    start(onMessage: (buffer: ArrayBuffer) => void): void | Promise<void>;
    /** Stop delivering and release resources. */
    stop(): void;
}
