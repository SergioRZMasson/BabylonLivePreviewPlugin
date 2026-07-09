add_executable(blp_headless_render main.cpp)

target_link_libraries(blp_headless_render PRIVATE BabylonLivePreviewCore)

if(WIN32)
    target_compile_definitions(blp_headless_render PRIVATE NOMINMAX WIN32_LEAN_AND_MEAN)
endif()

set_property(TARGET blp_headless_render PROPERTY FOLDER "BabylonLivePreview")

# Stage the JS bundle into "<exe dir>/Scripts" and copy Babylon Native / V8 DLLs.
blp_stage_scripts_for(blp_headless_render)
blp_build_live_script(blp_headless_render test)
blp_copy_runtime_dlls(blp_headless_render)
