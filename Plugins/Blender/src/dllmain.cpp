// Entry point for the Blender C-API DLL. The exported blp_* functions come from
// the linked static core (see exports.def); this translation unit only provides
// the module entry point.
#ifdef _WIN32
#include <Windows.h>

BOOL APIENTRY DllMain(HMODULE /*module*/, DWORD /*reason*/, LPVOID /*reserved*/)
{
    return TRUE;
}
#endif
