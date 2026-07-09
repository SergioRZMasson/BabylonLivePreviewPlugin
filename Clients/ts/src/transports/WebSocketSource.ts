// ===========================================================================
// Babylon Live Sync — WebSocket transport
// ===========================================================================
// Receives binary scene-delta frames from a server (e.g. an Omniverse/USD
// bridge) and forwards them to a SceneApplier. Auto-reconnects with backoff.
import { Source } from "./Source";

export interface WebSocketSourceOptions {
    /** Reconnect delay in ms (default 2000). Set 0 to disable reconnect. */
    reconnectDelayMs?: number;
    /** Optional subprotocols passed to the WebSocket constructor. */
    protocols?: string | string[];
}

export class WebSocketSource implements Source {
    private readonly url: string;
    private readonly opts: WebSocketSourceOptions;
    private ws: WebSocket | null = null;
    private onMessage: ((buffer: ArrayBuffer) => void) | null = null;
    private stopped = false;
    private reconnectTimer: ReturnType<typeof setTimeout> | null = null;

    constructor(url: string, options: WebSocketSourceOptions = {}) {
        this.url = url;
        this.opts = options;
    }

    start(onMessage: (buffer: ArrayBuffer) => void): void {
        this.onMessage = onMessage;
        this.stopped = false;
        this.connect();
    }

    stop(): void {
        this.stopped = true;
        if (this.reconnectTimer) {
            clearTimeout(this.reconnectTimer);
            this.reconnectTimer = null;
        }
        if (this.ws) {
            try { this.ws.close(); } catch { /* ignore */ }
            this.ws = null;
        }
    }

    private connect(): void {
        const ws = new WebSocket(this.url, this.opts.protocols);
        ws.binaryType = "arraybuffer";
        this.ws = ws;

        ws.onmessage = (ev: MessageEvent) => {
            if (!this.onMessage) {
                return;
            }
            const data = ev.data;
            if (data instanceof ArrayBuffer) {
                this.onMessage(data);
            } else if (typeof Blob !== "undefined" && data instanceof Blob) {
                data.arrayBuffer().then((buf) => this.onMessage && this.onMessage(buf));
            }
        };

        ws.onclose = () => {
            this.ws = null;
            this.scheduleReconnect();
        };

        ws.onerror = () => {
            try { ws.close(); } catch { /* ignore */ }
        };
    }

    private scheduleReconnect(): void {
        const delay = this.opts.reconnectDelayMs ?? 2000;
        if (this.stopped || delay <= 0) {
            return;
        }
        this.reconnectTimer = setTimeout(() => this.connect(), delay);
    }
}
