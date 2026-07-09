// ===========================================================================
// Babylon Live Sync — native entry (bundled as each DCC's live_preview.js)
// ===========================================================================
// Loaded by Babylon Native after babylon.js. Boots the NativeHost, which creates
// the engine + scene + render loop and installs the C++ bridge globals. The
// build's --dcc define is embedded so a bundle can be identified/customised per
// host without forking the entry.
import { NativeHost } from "../NativeHost";

declare const BLP_DCC: string | undefined;

const dcc = (typeof BLP_DCC !== "undefined" && BLP_DCC) ? BLP_DCC : "native";
const host = new NativeHost();
(globalThis as unknown as { _blpHost: NativeHost })._blpHost = host;
console.log("[live_sync] native entry for '" + dcc + "'");
