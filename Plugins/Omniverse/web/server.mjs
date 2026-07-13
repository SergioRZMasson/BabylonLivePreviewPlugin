// ===========================================================================
// Babylon Live Sync demo — mock delta server
// ===========================================================================
// Serves the browser demo and broadcasts scene-delta buffers over WebSocket, so
// a Babylon.js page updates live with no page-specific scene code. Stands in for
// a real producer (e.g. a USD/Omniverse bridge).
//
//   node Plugins/Omniverse/web/server.mjs [--port 8080]
//   -> open http://localhost:8080
import http from "node:http";
import { readFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { parseArgs } from "node:util";
import { WebSocketServer } from "ws";
import { initialSnapshot, animationFrame } from "./deltas.mjs";

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(here, "..", "..", "..");

const { values } = parseArgs({ options: { port: { type: "string", default: "8080" } } });
const PORT = Number(values.port);

// Static files: the demo page, the Babylon engine, and the UMD bundle.
const STATIC = {
    "/": { path: resolve(here, "index.html"), type: "text/html" },
    "/index.html": { path: resolve(here, "index.html"), type: "text/html" },
    "/babylon.js": { path: resolve(repoRoot, "node_modules/babylonjs/babylon.js"), type: "text/javascript" },
    "/babylonjs.loaders.js": { path: resolve(repoRoot, "node_modules/babylonjs-loaders/babylonjs.loaders.min.js"), type: "text/javascript" },
    "/babylon-live-sync.umd.js": { path: resolve(repoRoot, "Clients/ts/dist/babylon-live-sync.umd.js"), type: "text/javascript" },
    "/baked.gltf": { path: resolve(here, "baked.gltf"), type: "model/gltf+json" },
};

const server = http.createServer(async (req, res) => {
    const pathname = new URL(req.url ?? "/", "http://localhost").pathname;
    const entry = STATIC[pathname];
    if (!entry) {
        res.writeHead(404);
        res.end("Not found");
        return;
    }
    try {
        const body = await readFile(entry.path);
        res.writeHead(200, { "Content-Type": entry.type });
        res.end(body);
    } catch (e) {
        res.writeHead(500);
        res.end("Error: " + e);
    }
});

const wss = new WebSocketServer({ server });

wss.on("connection", (ws) => {
    console.log("[server] client connected");
    ws.binaryType = "arraybuffer";

    // 1. Send the full initial scene.
    ws.send(initialSnapshot());

    // 2. Stream animation deltas at ~30 Hz.
    const start = Date.now();
    const timer = setInterval(() => {
        if (ws.readyState !== ws.OPEN) {
            return;
        }
        const t = (Date.now() - start) / 1000;
        ws.send(animationFrame(t));
    }, 33);

    ws.on("close", () => {
        clearInterval(timer);
        console.log("[server] client disconnected");
    });
});

server.listen(PORT, () => {
    console.log(`[server] http + ws on http://localhost:${PORT}  (open it in a browser)`);
});
