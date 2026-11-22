/* Unicode GUI entry point. All application paths are relative to this EXE,
   never to PATH or the caller's current directory. */
#ifndef UNICODE
#define UNICODE
#endif
#define _UNICODE
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <wchar.h>
#include <stdlib.h>

static int fail(const wchar_t *message, DWORD error) {
    wchar_t detail[512] = L"";
    wchar_t text[1600];
    if (error)
        FormatMessageW(FORMAT_MESSAGE_FROM_SYSTEM | FORMAT_MESSAGE_IGNORE_INSERTS,
                       NULL, error, 0, detail, 512, NULL);
    _snwprintf(text, 1600, L"%ls\n\n%ls", message, detail);
    text[1599] = 0;
    MessageBoxW(NULL, text, L"CSLA 学习助手", MB_OK | MB_ICONERROR);
    return 1;
}

int WINAPI wWinMain(HINSTANCE instance, HINSTANCE previous, PWSTR arguments, int show) {
    (void)instance; (void)previous; (void)show;
    wchar_t root[32768], python[32768], script[32768];
    DWORD length = GetModuleFileNameW(NULL, root, 32768);
    if (!length || length >= 32768)
        return fail(L"无法读取软件目录。", GetLastError());
    wchar_t *slash = wcsrchr(root, L'\\');
    if (!slash) return fail(L"软件目录无效。", 0);
    *slash = 0;
    if (wcslen(root) > 32000) return fail(L"软件路径过长，请解压到较短的目录。", 0);
    _snwprintf(python, 32768, L"%ls\\internal\\python\\pythonw.exe", root);
    _snwprintf(script, 32768, L"%ls\\internal\\desktop\\launcher.py", root);
    if (GetFileAttributesW(python) == INVALID_FILE_ATTRIBUTES ||
        GetFileAttributesW(script) == INVALID_FILE_ATTRIBUTES)
        return fail(L"软件文件缺失。请先完整解压 ZIP，再双击 CSLA.exe。\n"
                    L"请保留 CSLA.exe 旁边的 internal 文件夹。", 0);
    size_t size = wcslen(python) + wcslen(script) + wcslen(arguments) + 16;
    if (size >= 32767) return fail(L"启动参数或软件路径过长。", 0);
    wchar_t *command = calloc(size, sizeof(wchar_t));
    if (!command) return fail(L"内存不足。", ERROR_NOT_ENOUGH_MEMORY);
    _snwprintf(command, size, L"\"%ls\" -B \"%ls\" %ls", python, script, arguments);
    SetEnvironmentVariableW(L"PYTHONUTF8", L"1");
    SetEnvironmentVariableW(L"PYTHONNET_RUNTIME", L"netfx");

    /* Windows 10/11 allow nested jobs. Explicit breakaway remains available to
       the browser runtime; the embedded Python server stays in this job. */
    HANDLE job = CreateJobObjectW(NULL, NULL);
    JOBOBJECT_EXTENDED_LIMIT_INFORMATION limits = {0};
    limits.BasicLimitInformation.LimitFlags =
        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE | JOB_OBJECT_LIMIT_BREAKAWAY_OK;
    if (!job || !SetInformationJobObject(job, JobObjectExtendedLimitInformation,
                                         &limits, sizeof(limits))) {
        DWORD error = GetLastError();
        if (job) CloseHandle(job);
        free(command);
        return fail(L"无法初始化应用进程。", error);
    }
    STARTUPINFOW startup = {0};
    PROCESS_INFORMATION process = {0};
    startup.cb = sizeof(startup);
    BOOL created = CreateProcessW(python, command, NULL, NULL, FALSE,
        CREATE_NO_WINDOW | CREATE_SUSPENDED, NULL, root, &startup, &process);
    free(command);
    if (!created) {
        DWORD error = GetLastError();
        CloseHandle(job);
        return fail(L"无法启动内置 Python。请确认软件已完整解压。", error);
    }
    if (!AssignProcessToJobObject(job, process.hProcess)) {
        DWORD error = GetLastError();
        TerminateProcess(process.hProcess, 1);
        CloseHandle(process.hThread);
        CloseHandle(process.hProcess);
        CloseHandle(job);
        return fail(L"无法管理应用进程。", error);
    }
    ResumeThread(process.hThread);
    CloseHandle(process.hThread);
    WaitForSingleObject(process.hProcess, INFINITE);
    DWORD exit_code = 1;
    GetExitCodeProcess(process.hProcess, &exit_code);
    CloseHandle(process.hProcess);
    CloseHandle(job);
    if (exit_code)
        fail(L"应用未正常启动或已异常退出。\n请查看 "
             L"%LOCALAPPDATA%\\CSLA Desktop\\desktop.log。", 0);
    return (int)exit_code;
}
