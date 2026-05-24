cmake_minimum_required(VERSION 3.21)
project(foxport_abe CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>")

if(NOT WIN32)
    message(FATAL_ERROR "foxport_abe.exe is Windows-only — its whole purpose is DPAPI/IElevator.")
endif()

add_executable(foxport_abe WIN32 foxport_abe.cpp)
set_target_properties(foxport_abe PROPERTIES
    OUTPUT_NAME "foxport_abe"
    WIN32_EXECUTABLE FALSE          # console subsystem — we read stdout
)

target_compile_definitions(foxport_abe PRIVATE
    UNICODE _UNICODE
    WIN32_LEAN_AND_MEAN
    NOMINMAX
)

target_link_libraries(foxport_abe PRIVATE
    crypt32
    ole32
    oleaut32
)

# Embed a manifest requesting requireAdministrator. Without elevation, the
# IElevator COM activation will return E_ACCESSDENIED.
set(MANIFEST_FILE "${CMAKE_CURRENT_SOURCE_DIR}/foxport_abe.exe.manifest")
target_sources(foxport_abe PRIVATE ${MANIFEST_FILE})
