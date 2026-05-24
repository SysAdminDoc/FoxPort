// foxport_abe.exe — App-Bound Encryption key recovery sidecar for FoxPort.
//
// Background: Chrome 127+ (and Brave 1.86+) added App-Bound Encryption (ABE),
// which wraps the cookie/payment master key in a *second* DPAPI layer that
// is bound to the Chrome install path and elevated COM identity. The wrapped
// key lives in Local State as os_crypt.app_bound_encrypted_key (base64,
// prefixed "APPB").
//
// Recovery sequence (xaitax / runassu research):
//   1. base64-decode app_bound_encrypted_key, strip "APPB" prefix
//   2. CryptUnprotectData in SYSTEM context  -> intermediate blob
//   3. CryptUnprotectData in USER  context   -> 32-byte AES-256 key
//
// Step 2 requires either:
//   (a) running as SYSTEM (we can't from a UAC prompt alone), OR
//   (b) calling the per-browser IElevator COM interface (registered as
//       elevated, requires admin) and asking it to do the inner unprotect.
//
// This sidecar implements (b). It's invoked from Python as:
//   foxport_abe.exe --browser chrome --local-state "C:\path\to\Local State"
//
// On success, prints two lines on stdout:
//   KEY_HEX:<64-hex-chars>
//   OK
// and exits 0.
//
// On failure, prints one or more diagnostic lines on stderr and exits non-zero.
//
// Build: see CMakeLists.txt — needs MSVC v143, Windows SDK 10.0.22621+,
// /std:c++20, /MD, link comctl32.lib + crypt32.lib + ole32.lib + oleaut32.lib.

#define _CRT_SECURE_NO_WARNINGS
#include <windows.h>
#include <wincrypt.h>
#include <objbase.h>
#include <oleauto.h>
#include <shellapi.h>

#include <cstdio>
#include <cstdint>
#include <cstring>
#include <string>
#include <vector>
#include <fstream>
#include <sstream>

#pragma comment(lib, "crypt32.lib")
#pragma comment(lib, "ole32.lib")
#pragma comment(lib, "oleaut32.lib")

// ---- Per-vendor IElevator class + interface IDs (from xaitax research) ----
// Chrome stable IElevator
static const CLSID CLSID_ELEVATOR_CHROME =
    {0x708860E0, 0xF641, 0x4611, {0x88, 0x95, 0x7D, 0x86, 0x7D, 0xD3, 0x67, 0x5B}};
static const IID   IID_IELEVATOR_CHROME  =
    {0x463ABECF, 0x410D, 0x407F, {0x8A, 0xF5, 0x0D, 0xF3, 0x5A, 0x00, 0x5C, 0xC8}};

// Brave IElevator (different IID, same vtbl layout as Chrome)
static const CLSID CLSID_ELEVATOR_BRAVE  =
    {0x576B31AF, 0x6369, 0x4B6B, {0x85, 0x60, 0xE4, 0xB2, 0x03, 0xA9, 0x7A, 0x8B}};
static const IID   IID_IELEVATOR_BRAVE   =
    {0xF396861E, 0x0C8E, 0x4C71, {0x82, 0x56, 0x2F, 0xAE, 0x6D, 0x75, 0x9C, 0xE9}};

// Edge IElevatorEdge (different vtbl entirely)
static const CLSID CLSID_ELEVATOR_EDGE   =
    {0x1FCBE96C, 0x1697, 0x43AF, {0x91, 0x40, 0x28, 0x97, 0xC7, 0xC6, 0x97, 0x67}};
static const IID   IID_IELEVATOR_EDGE    =
    {0xC9C2B807, 0x7731, 0x4F34, {0x81, 0xB7, 0x44, 0xFF, 0x77, 0x79, 0x52, 0x2B}};

// IElevator vtable (Chrome layout — Brave matches; Edge has its own).
// We declare only the slots up to DecryptData (offset 4 in the vtbl).
struct IElevator : public IUnknown {
    virtual HRESULT STDMETHODCALLTYPE RunRecoveryCRXElevated(
        const wchar_t* crx_path,
        const wchar_t* browser_appid,
        const wchar_t* browser_version,
        const wchar_t* session_id,
        DWORD caller_proc_id,
        ULONG_PTR* proc_handle) = 0;
    virtual HRESULT STDMETHODCALLTYPE EncryptData(
        int protection_level,
        const BSTR plaintext,
        BSTR* ciphertext,
        DWORD* last_error) = 0;
    virtual HRESULT STDMETHODCALLTYPE DecryptData(
        const BSTR ciphertext,
        BSTR* plaintext,
        DWORD* last_error) = 0;
};

// ----------------- Base64 (avoid linking CryptStringToBinary deps) ----------

static const char B64_ALPHA[] =
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

static bool b64decode(const std::string& input, std::vector<uint8_t>& out) {
    int t[256];
    for (int i = 0; i < 256; ++i) t[i] = -1;
    for (int i = 0; i < 64;  ++i) t[(unsigned char)B64_ALPHA[i]] = i;
    out.clear();
    int val = 0, bits = 0;
    for (char c : input) {
        if (c == '=' || c == '\r' || c == '\n' || c == ' ' || c == '\t') {
            if (c == '=') break;
            continue;
        }
        int v = t[(unsigned char)c];
        if (v < 0) return false;
        val = (val << 6) | v;
        bits += 6;
        if (bits >= 8) {
            bits -= 8;
            out.push_back((uint8_t)((val >> bits) & 0xFF));
        }
    }
    return true;
}

// ----------------- File I/O helpers -----------------------------------------

static bool read_file_utf8(const std::wstring& path, std::string& out) {
    std::ifstream ifs(path, std::ios::binary);
    if (!ifs) return false;
    std::stringstream ss;
    ss << ifs.rdbuf();
    out = ss.str();
    return true;
}

// Extract a top-level JSON string value. NOT a full parser; targets
// os_crypt.app_bound_encrypted_key only.
static bool extract_json_string(const std::string& body, const std::string& key,
                                std::string& out) {
    std::string needle = "\"" + key + "\"";
    size_t pos = body.find(needle);
    if (pos == std::string::npos) return false;
    pos = body.find(':', pos);
    if (pos == std::string::npos) return false;
    pos = body.find('"', pos);
    if (pos == std::string::npos) return false;
    ++pos;
    size_t end = body.find('"', pos);
    if (end == std::string::npos) return false;
    out = body.substr(pos, end - pos);
    return true;
}

// ----------------- DPAPI unprotect ------------------------------------------

static bool dpapi_unprotect(const std::vector<uint8_t>& in,
                            std::vector<uint8_t>& out, std::string& err) {
    DATA_BLOB inb = { (DWORD)in.size(), const_cast<BYTE*>(in.data()) };
    DATA_BLOB outb = { 0 };
    if (!CryptUnprotectData(&inb, nullptr, nullptr, nullptr, nullptr, 0, &outb)) {
        DWORD e = GetLastError();
        char buf[128];
        sprintf(buf, "CryptUnprotectData failed: 0x%08lX", (unsigned long)e);
        err = buf;
        return false;
    }
    out.assign(outb.pbData, outb.pbData + outb.cbData);
    LocalFree(outb.pbData);
    return true;
}

// ----------------- Main entry ------------------------------------------------

static void print_usage() {
    fprintf(stderr,
        "Usage: foxport_abe.exe --browser {chrome|brave|edge} --local-state <path>\n"
        "\n"
        "Recovers the App-Bound Encryption master key from a Chromium-family\n"
        "Local State file. Requires elevation (Run as administrator).\n");
}

int wmain(int argc, wchar_t* argv[]) {
    std::wstring browser, local_state;
    for (int i = 1; i + 1 < argc; i += 2) {
        if (wcscmp(argv[i], L"--browser") == 0)      browser = argv[i + 1];
        else if (wcscmp(argv[i], L"--local-state") == 0) local_state = argv[i + 1];
    }
    if (browser.empty() || local_state.empty()) {
        print_usage();
        return 2;
    }

    // 1. Read Local State + extract app_bound_encrypted_key
    std::string body;
    if (!read_file_utf8(local_state, body)) {
        fprintf(stderr, "ERROR: cannot read Local State at %ls\n", local_state.c_str());
        return 3;
    }
    std::string b64;
    if (!extract_json_string(body, "app_bound_encrypted_key", b64)) {
        fprintf(stderr, "ERROR: os_crypt.app_bound_encrypted_key not found\n");
        return 4;
    }
    std::vector<uint8_t> wrapped;
    if (!b64decode(b64, wrapped) || wrapped.size() < 5 ||
        wrapped[0] != 'A' || wrapped[1] != 'P' || wrapped[2] != 'P' || wrapped[3] != 'B') {
        fprintf(stderr, "ERROR: encrypted key blob missing APPB prefix\n");
        return 5;
    }
    std::vector<uint8_t> abe_blob(wrapped.begin() + 4, wrapped.end());

    // 2. Pick the right elevator class/interface
    CLSID clsid; IID iid;
    if (browser == L"chrome")      { clsid = CLSID_ELEVATOR_CHROME; iid = IID_IELEVATOR_CHROME; }
    else if (browser == L"brave")  { clsid = CLSID_ELEVATOR_BRAVE;  iid = IID_IELEVATOR_BRAVE;  }
    else if (browser == L"edge")   { clsid = CLSID_ELEVATOR_EDGE;   iid = IID_IELEVATOR_EDGE;   }
    else {
        fprintf(stderr, "ERROR: unknown --browser %ls\n", browser.c_str());
        return 6;
    }

    // 3. Call DecryptData on the elevated COM object.
    if (FAILED(CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED))) {
        fprintf(stderr, "ERROR: CoInitializeEx failed\n");
        return 7;
    }

    BIND_OPTS3 bo = {};
    bo.cbStruct = sizeof(bo);
    bo.dwClassContext = CLSCTX_LOCAL_SERVER;

    IElevator* elevator = nullptr;
    HRESULT hr = CoGetObject(nullptr, &bo, iid, (void**)&elevator);
    if (FAILED(hr) || !elevator) {
        // Fall back to standard CoCreateInstance (works when sidecar is already elevated).
        hr = CoCreateInstance(clsid, nullptr, CLSCTX_LOCAL_SERVER, iid, (void**)&elevator);
    }
    if (FAILED(hr) || !elevator) {
        fprintf(stderr, "ERROR: CoCreateInstance(IElevator) failed: 0x%08lX\n", hr);
        CoUninitialize();
        return 8;
    }

    // BSTR is a 2-byte counted blob; allocate from raw bytes.
    BSTR cipher_bstr = SysAllocStringByteLen((const char*)abe_blob.data(),
                                             (UINT)abe_blob.size());
    BSTR plain_bstr = nullptr;
    DWORD last_err = 0;
    hr = elevator->DecryptData(cipher_bstr, &plain_bstr, &last_err);
    SysFreeString(cipher_bstr);
    elevator->Release();

    if (FAILED(hr) || !plain_bstr) {
        fprintf(stderr, "ERROR: IElevator::DecryptData failed: hr=0x%08lX last_error=0x%08lX\n",
                hr, last_err);
        CoUninitialize();
        return 9;
    }

    UINT plain_len = SysStringByteLen(plain_bstr);
    std::vector<uint8_t> intermediate((uint8_t*)plain_bstr,
                                      (uint8_t*)plain_bstr + plain_len);
    SysFreeString(plain_bstr);

    // 4. The intermediate blob is still wrapped in user-context DPAPI.
    //    Unwrap that to get the 32-byte AES key.
    std::vector<uint8_t> final_key;
    std::string err;
    if (!dpapi_unprotect(intermediate, final_key, err)) {
        fprintf(stderr, "ERROR: inner DPAPI unprotect failed: %s\n", err.c_str());
        CoUninitialize();
        return 10;
    }

    // Chrome's elevator returns "[install_path]<flag><iv><ciphertext><tag>" --
    // the trailing 32 bytes after a 0x01 flag is what we want. For some
    // build variants the response is already just the 32-byte key.
    std::vector<uint8_t> key;
    if (final_key.size() == 32) {
        key = final_key;
    } else if (final_key.size() >= 32) {
        key.assign(final_key.end() - 32, final_key.end());
    } else {
        fprintf(stderr, "ERROR: inner blob too short (%zu bytes)\n", final_key.size());
        CoUninitialize();
        return 11;
    }

    static const char hex[] = "0123456789abcdef";
    char keyhex[65] = {0};
    for (size_t i = 0; i < 32; ++i) {
        keyhex[i * 2 + 0] = hex[key[i] >> 4];
        keyhex[i * 2 + 1] = hex[key[i] & 0xF];
    }
    printf("KEY_HEX:%s\n", keyhex);
    printf("OK\n");

    CoUninitialize();
    return 0;
}
