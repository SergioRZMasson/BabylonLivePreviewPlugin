// ===========================================================================
// BabylonLivePreview — opt-in crash stack tracer (Windows)
// ===========================================================================
// When the environment variable BLP_CRASH_TRACE is set, installs a vectored
// exception handler that prints a symbolized stack for the first access
// violation, then lets the process continue crashing. Diagnostic aid for
// in-host (e.g. inside a DCC) failures; a no-op unless the env var is set.
#ifdef _WIN32
#include <Windows.h>
#include <DbgHelp.h>
#include <cstdio>

#pragma comment(lib, "dbghelp.lib")

namespace
{
    LONG WINAPI BlpVectoredHandler(EXCEPTION_POINTERS* info)
    {
        if (info->ExceptionRecord->ExceptionCode != EXCEPTION_ACCESS_VIOLATION)
        {
            return EXCEPTION_CONTINUE_SEARCH;
        }

        HANDLE process = ::GetCurrentProcess();
        ::SymSetOptions(SYMOPT_UNDNAME | SYMOPT_DEFERRED_LOADS | SYMOPT_LOAD_LINES);
        ::SymInitialize(process, nullptr, TRUE);

        std::fprintf(stderr, "[BLP-CRASH] access violation at %p (reading %p)\n",
            info->ExceptionRecord->ExceptionAddress,
            reinterpret_cast<void*>(info->ExceptionRecord->ExceptionInformation[1]));

        void* frames[48];
        const USHORT count = ::CaptureStackBackTrace(0, 48, frames, nullptr);

        alignas(SYMBOL_INFO) char symbolBuffer[sizeof(SYMBOL_INFO) + 256] = {};
        SYMBOL_INFO* symbol = reinterpret_cast<SYMBOL_INFO*>(symbolBuffer);
        symbol->SizeOfStruct = sizeof(SYMBOL_INFO);
        symbol->MaxNameLen = 255;

        for (USHORT i = 0; i < count; ++i)
        {
            char moduleName[MAX_PATH] = "?";
            HMODULE module = nullptr;
            if (::GetModuleHandleExA(
                    GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                    reinterpret_cast<LPCSTR>(frames[i]), &module) && module)
            {
                ::GetModuleFileNameA(module, moduleName, MAX_PATH);
            }

            DWORD64 displacement = 0;
            if (::SymFromAddr(process, reinterpret_cast<DWORD64>(frames[i]), &displacement, symbol))
            {
                std::fprintf(stderr, "[BLP-CRASH]  %2u  %p  %s+0x%llx  [%s]\n",
                    i, frames[i], symbol->Name, static_cast<unsigned long long>(displacement), moduleName);
            }
            else
            {
                std::fprintf(stderr, "[BLP-CRASH]  %2u  %p  [%s]\n", i, frames[i], moduleName);
            }
        }
        std::fflush(stderr);
        return EXCEPTION_CONTINUE_SEARCH;
    }

    struct BlpCrashTraceInstaller
    {
        BlpCrashTraceInstaller()
        {
            if (::GetEnvironmentVariableA("BLP_CRASH_TRACE", nullptr, 0) != 0)
            {
                ::AddVectoredExceptionHandler(1, BlpVectoredHandler);
            }
        }
    };

    BlpCrashTraceInstaller s_installer;
}
#endif
