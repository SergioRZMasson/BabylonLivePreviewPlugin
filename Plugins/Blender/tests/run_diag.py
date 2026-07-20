"""Diagnose PBR/env/BRDF state inside the running Babylon session.

    python Plugins/Blender/tests/run_diag.py

Renders the default scene, then uses blp_eval to report environmentTexture,
BRDF texture readiness, image-processing settings, and any material state, so we
can see WHY the model looks wrong. Also samples the readback gamma.
"""

import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.abspath(os.path.join(_HERE, "..", "..", ".."))
_ADDON = os.path.join(_REPO, "Plugins", "Blender", "addon", "babylon_live_preview")
sys.path.insert(0, _ADDON)

import bridge   # noqa: E402


def default_dll():
    # Cross-platform: resolve the built native module (.dll/.dylib/.so) across
    # multi-config (Windows) and single-config (macOS/Linux) build trees.
    return bridge.default_build_library(_REPO)


def main():
    dll = default_dll()
    b = bridge.BabylonBridge(dll)
    if not b.create(640, 480, os.path.join(os.path.dirname(dll), "Scripts")):
        print("[diag] FAILED: blp_create")
        return 2
    for _ in range(3000):
        b.render_frame()
        if b.is_ready():
            break
        time.sleep(0.01)
    # let env + effects settle
    for _ in range(60):
        b.render_frame(); time.sleep(0.01)

    # Report diagnostic state to the console via blp_eval.
    diag = (
        "(function(){"
        "var s=currentScene;"
        "var r=['DIAG'];"
        "r.push('scene='+(!!s));"
        "r.push('envTex='+(s&&s.environmentTexture?s.environmentTexture.getClassName():'NONE'));"
        "r.push('envReady='+(s&&s.environmentTexture?s.environmentTexture.isReady():'n/a'));"
        "r.push('ip.toneMap='+(s?s.imageProcessingConfiguration.toneMappingEnabled:'?'));"
        "r.push('ip.toneType='+(s?s.imageProcessingConfiguration.toneMappingType:'?'));"
        "r.push('meshes='+(s?s.meshes.length:0));"
        "var m=s&&s.meshes.length?s.meshes[0].material:null;"
        "r.push('mat0='+(m?m.getClassName():'NONE'));"
        "if(m){r.push('mat0.env='+(m.environmentTexture?'own':'sceneDefault'));}"
        "var brdf=null;try{brdf=BABYLON.Constants?('haveConst'):'noConst';}catch(e){}"
        "if(s&&s.meshes.length){var pbr=null;for(var i=0;i<s.meshes.length;i++){var mm=s.meshes[i].material;if(mm&&mm.getClassName().indexOf('PBR')>=0){pbr=mm;break;}}"
        "if(pbr){r.push('pbr.brdf='+(pbr._environmentBRDFTexture?(pbr._environmentBRDFTexture.isReady?('ready='+pbr._environmentBRDFTexture.isReady()):'exists'):'NULL'));}}"
        "r.push('BABYLON.Tools.UseFallbackTexture='+BABYLON.Tools.UseFallbackTexture);"
        "r.push('XMLHttpRequest='+(typeof XMLHttpRequest));"
        "r.push('URL='+(typeof URL));"
        "r.push('fetch='+(typeof fetch));"
        "console.log(r.join(' | '));"
        "})()"
    )
    b.eval(diag)
    for _ in range(30):
        b.render_frame(); time.sleep(0.02)

    # Sample the readback to check brightness/gamma of the default scene.
    b.request_readback()
    res = None
    for _ in range(400):
        b.render_frame()
        res = b.try_acquire_readback()
        if res:
            break
        time.sleep(0.008)
    if res:
        data, w, h = res
        cx = (h // 2 * w + w // 2) * 4
        print("[diag] center pixel RGBA = [%d,%d,%d,%d]" %
              (data[cx], data[cx + 1], data[cx + 2], data[cx + 3]))
    b.destroy()
    return 0


if __name__ == "__main__":
    sys.exit(main())
