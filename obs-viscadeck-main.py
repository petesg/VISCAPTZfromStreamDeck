import configparser
import obspython as obs
import ptz
import buttons
import json
from types import SimpleNamespace

# cameraScenes = ["", ""]
cameras = []
loadedConfig = None

configPath = ""

# intrinsics
# ----------

# populates script UI description field
def scipt_description():
    return "Synchronizes OBS scene transitions with camera movements from on Stream Deck input (bypasses Elgato software)."

# script setup (as OBS itself is booting up)
# def script_load(settings):
#     pass

# def script_unload():
#     pass

# def script_save(settings):
#     pass

# def script_defaults(settings):
#     pass

# runs any time properties are changed by the user
def script_update(settings):
    # global cameraScenes
    global configPath
    global cameras
    global loadedConfig

    configPath = obs.obs_data_get_string(settings, "picker_configPath")
    # reconfigure with new json TODO: do something if path is empty
    # if not configureMain():
    #     # TODO we should probably do something if this fails right?
    #     pass

    # TODO add/remove scene pickers based on potentially different number of cameras

    # for i in range(len(cameras)):
    for camera in cameras:
        camera.sceneName = obs.obs_data_get_string(settings, f"picker_cam_camera.name")

# sets up property setter UI elements
def script_properties():
    global cameras
    global loadedConfig
    props = obs.obs_properties_create()

    obs.obs_properties_add_path(props, "picker_configPath", "Config file", obs.OBS_PATH_FILE, "JSON files (*.json)", None)

    if not configureMain():
        #obs.obs_properties_add_text(props, "errorText", "Config file error!  Please fix and refresh script.", obs.OBS_TEXT_INFO_ERROR)
        return props
    print(f"config loaded: {loadedConfig}")

    scenes = obs.obs_frontend_get_scenes()
    
    print(f"configuring user properties for {len(cameras)} cameras")
    for camera in cameras:
        p = obs.obs_properties_add_list(props, f"picker_cam_{camera.name}", f'Cam: "{camera.name}"', obs.OBS_COMBO_TYPE_LIST, obs.OBS_COMBO_FORMAT_STRING)
        for scene in scenes:
            name = obs.obs_source_get_name(scene)
            obs.obs_property_list_add_string(p, name, name)
    
    obs.obs_properties_add_button(props, "testNearButton", "Near [TEMP]", testNearButton_callback)
    obs.obs_properties_add_button(props, "testFarButton", "Far [TEMP]", testFarButton_callback)
    
    return props

# def script_tick(seconds):
#     pass

# system
# ------

def configureMain():
    global loadedConfig
    global cameras
    loadedConfig = None
    cameras = []
    print("loading config...")
    try:
        with open(configPath) as configFile:
            jsonData = configFile.read()
        loadedConfig = json.loads(jsonData, object_hook=lambda d: SimpleNamespace(**d))
    except FileNotFoundError:
        return False
    print("config loaded")

    # load cameras
    try:
        print(f"{len(loadedConfig.Cameras)} cameras & {len(loadedConfig.Presets)} presets detected")
        for camera in loadedConfig.Cameras:
            newCam = ptz.Camera(camera.ip, camera.port, camera.channel, camera.name)
            newCam.sceneName = "" # add property to hold scene name
            cameras.append(newCam)
        print(f"{len(cameras)} cameras loaded")
    except AttributeError:
        return False
    
    # 

    # setup streamdeck
    buttons.configureDeck(configPath)

    return True

def getLiveCamera():
    current_scene = obs.obs_frontend_get_current_scene()
    # currentScene = obs.obs_scene_from_source(current_scene)
    for camera in cameras:
        if camera.sceneName == obs.obs_source_get_name(current_scene):
            return camera
    return None # TODO maybe throw an exception???

# callbacks
# ---------

def callPreset_callback(presetIndex):
    # TODO
    pass
    # scenes = obs.obs_frontend_get_scenes()
    # for scene in scenes:
    #     name = obs.obs_source_get_name(scene)
    #     if name == cameraScenes[camIndex]:
    #         obs.obs_frontend_set_current_scene(scene)

def testNearButton_callback(props, prop):
    callPreset_callback(0)

def testFarButton_callback(props, prop):
    callPreset_callback(1)