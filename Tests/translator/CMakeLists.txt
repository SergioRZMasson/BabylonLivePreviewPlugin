add_executable(blp_translator main.cpp
    ${CMAKE_SOURCE_DIR}/Shared/src/SceneTranslation.cpp
    ${CMAKE_SOURCE_DIR}/Shared/src/SceneProtocol.cpp)

target_include_directories(blp_translator PRIVATE ${CMAKE_SOURCE_DIR}/Shared/include)

target_compile_features(blp_translator PRIVATE cxx_std_20)

if(WIN32)
    target_compile_definitions(blp_translator PRIVATE NOMINMAX WIN32_LEAN_AND_MEAN)
endif()

set_property(TARGET blp_translator PROPERTY FOLDER "BabylonLivePreview")

# No Babylon Native / JS bundle needed: the translation layer is pure protocol.
add_test(NAME blp_translator COMMAND blp_translator)
