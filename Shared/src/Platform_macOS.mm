// ===========================================================================
// BabylonLivePreview — macOS platform surface (Metal)
// ===========================================================================
// On Windows the core hands bgfx a hidden HWND so it creates a swapchain whose
// backbuffer RequestScreenShot can read back. On macOS the equivalent surface
// is a CAMetalLayer: bgfx's Metal renderer runs *headless* (no readable
// backbuffer) when given a null window, so we create an off-screen
// CAMetalLayer and hand it to bgfx as the native window. `framebufferOnly = NO`
// is required so the screenshot blit (synchronizeResource + getBytes) can read
// the drawable back to CPU memory.
//
// Compiled without ARC (manual retain/release): the returned layer carries a
// +1 reference owned by the caller and freed via BlpReleaseMetalLayer.
#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#import <QuartzCore/CAMetalLayer.h>

#include <cstdint>

extern "C" void* BlpCreateOffscreenMetalLayer(uint32_t width, uint32_t height)
{
    CAMetalLayer* layer = [[CAMetalLayer alloc] init]; // +1 (MRC)

    id<MTLDevice> device = MTLCreateSystemDefaultDevice(); // +1
    if (device != nil)
    {
        layer.device = device; // layer retains it
        [device release];
    }

    layer.pixelFormat = MTLPixelFormatBGRA8Unorm; // bgfx's default backbuffer format
    layer.framebufferOnly = NO;                   // allow CPU readback of the drawable
    layer.drawableSize = CGSizeMake(static_cast<CGFloat>(width ? width : 1),
                                    static_cast<CGFloat>(height ? height : 1));

    return static_cast<void*>(layer); // caller owns the +1
}

extern "C" void BlpReleaseMetalLayer(void* layer)
{
    if (layer != nullptr)
    {
        [static_cast<CAMetalLayer*>(layer) release];
    }
}
