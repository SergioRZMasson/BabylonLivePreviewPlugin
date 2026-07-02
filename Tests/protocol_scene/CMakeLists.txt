add_executable(blp_protocol_scene main.cpp)

target_link_libraries(blp_protocol_scene PRIVATE BabylonLivePreviewCore)

if(WIN32)
    target_compile_definitions(blp_protocol_scene PRIVATE NOMINMAX WIN32_LEAN_AND_MEAN)
endif()

set_property(TARGET blp_protocol_scene PROPERTY FOLDER "BabylonLivePreview")

blp_stage_scripts_for(blp_protocol_scene)
blp_copy_runtime_dlls(blp_protocol_scene)
