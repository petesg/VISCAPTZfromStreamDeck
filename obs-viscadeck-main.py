# add "<obs-studio install dir>\\data\\obs-scripting\\64bit" to "python.analysis.extraPaths": [] in settings.json
import obspython as obs
import ptz
import buttons
import json
import importlib
import time
from types import SimpleNamespace

# cameraScenes = ["", ""]
cameras = []
otherScenes = {}
loadedConfig = None
loadSuccess = False
configPath = ""
delayDur = 0
deck = None

# intrinsics
# ----------

# populates script UI description field
def script_description():
    return "Synchronizes OBS scene transitions with camera movements on command via Stream Deck (bypasses Elgato software)."

# script setup (as OBS itself is booting up)
def script_load(settings):
    global configPath
    global loadSuccess
    global delayDur
    print("(load)")

    configPath = obs.obs_data_get_string(settings, "picker_configPath")
    delayDur = obs.obs_data_get_int(settings, "picker_delay")
    loadSuccess = configureMain()
    print(f'delaydur is {delayDur}')
    print(f"config loaded: {loadedConfig}")
    # configureMain()
    # print(f'"settings" = {{{settings}}}')
    # global loadSuccess
    # global configPath
    # try:
    #     configPath = settings.configPath
    #     print(f"preloaded configpath {configPath}")
    # except AttributeError:
    #     print(f"no configpath to preload")
    # loadSuccess = configureMain()

def script_unload():
    global deck
    print('(unload)')
    if deck:
        deck.close()

def script_save(settings):
    print("(save)")
    # global configPath
    # settings.configPath = configPath
    # print("saved")
    # if deck:
    #     deck.close()

def script_defaults(settings):
    print("(defaults)")
    importlib.reload(ptz)
    importlib.reload(buttons)
    print("local modules reloaded")


# runs any time properties are changed by the user
def script_update(settings):
    # global cameraScenes
    global configPath
    global cameras
    global loadedConfig
    global otherScenes
    # global loadSuccess

    print("(update)")

    configPath = obs.obs_data_get_string(settings, "picker_configPath")
    # TODO: do something if path is empty
    # reconfigure with new json (TODO should I be doing something here)
    # if not loadSuccess: # this 
    #     if not configureMain():
    #         # TODO we should probably do something if this fails right?
    #         pass

    # TODO add/remove scene pickers based on potentially different number of cameras
    # ^ (I don't think this is possible actually?  gotta rely on user reloading script when changed)

    if not loadedConfig:
        return

    # for i in range(len(cameras)):
    for camera in cameras:
        camera.sceneName = obs.obs_data_get_string(settings, f"picker_cam_{camera.name}")
    
    for escene in loadedConfig.ExtraScenes.__dict__:
        otherScenes[escene] = obs.obs_data_get_string(settings, f'picker_escene_{escene}')

# sets up property setter UI elements
def script_properties():
    global cameras
    global loadedConfig
    global loadSuccess

    print("(props)")

    props = obs.obs_properties_create()

    p = obs.obs_properties_add_path(props, "picker_configPath", "Config File", obs.OBS_PATH_FILE, "JSON files (*.json)", None)
    obs.obs_property_set_long_description(p, "JSON system config file")
    obs.obs_property_set_modified_callback(p, configFileChanged_callback)

    if not loadSuccess: # configureMain():
        #obs.obs_properties_add_text(props, "errorText", "Config file error!  Please fix and refresh script.", obs.OBS_TEXT_INFO_ERROR)
        return props

    scenes = obs.obs_frontend_get_scenes()
    print(f"configuring user properties for {len(cameras)} cameras")
    for camera in cameras:
        p = obs.obs_properties_add_list(props, f"picker_cam_{camera.name}", f'"{camera.name}" Camera', obs.OBS_COMBO_TYPE_LIST, obs.OBS_COMBO_FORMAT_STRING)
        obs.obs_property_set_long_description(p, f'Scene corresponding to  "{camera.name}" camera')
        for scene in scenes:
            name = obs.obs_source_get_name(scene)
            obs.obs_property_list_add_string(p, name, name)
    
    for extraScene in loadedConfig.ExtraScenes.__dict__:
        p = obs.obs_properties_add_list(props, f"picker_escene_{extraScene}", f'"{extraScene}" Scene', obs.OBS_COMBO_TYPE_LIST, obs.OBS_COMBO_FORMAT_STRING)
        obs.obs_property_set_long_description(p, f'Scene corresponding to "{extraScene}"')
        for scene in scenes:
            name = obs.obs_source_get_name(scene)
            obs.obs_property_list_add_string(p, name, name)

    p = obs.obs_properties_add_int(props, "picker_delay", "Lag Comp. (ms)", 0, 10000, 10)
    obs.obs_property_set_modified_callback(p, delayDurChanged_callback)
    obs.obs_property_set_long_description(p, 'Compoensation delay for network lag in video feed')

    # obs.obs_properties_add_button(props, "testNearButton", "Near [TEMP]", testNearButton_callback)
    # obs.obs_properties_add_button(props, "testFarButton", "Far [TEMP]", testFarButton_callback)
    
    # script_update(None)

    return props

# def script_tick(seconds):
#     pass

# system
# ------

def configureMain():
    global loadedConfig
    global cameras
    global deck
    loadedConfig = None
    cameras = []
    print("loading config...")
    try:
        with open(configPath) as configFile:
            jsonData = configFile.read()
        loadedConfig = json.loads(jsonData, object_hook=lambda d: SimpleNamespace(**d))
    except FileNotFoundError as e:
        print(e)
        return False
    print("config loaded")

    # load cameras
    try:
        print(f"{len(loadedConfig.Cameras)} cameras & {len(loadedConfig.Presets.__dict__)} presets detected")
        for camera in loadedConfig.Cameras:
            newCam = ptz.Camera(camera.ip, camera.port, camera.channel, camera.name)
            newCam.sceneName = "" # add property to hold scene name
            cameras.append(newCam)
        print(f"{len(cameras)} cameras loaded")
    except AttributeError:
        return False

    # setup streamdeck
    deck = buttons.ViscaDeck(loadedConfig, callPreset_callback, callScene_callback, toggleStream_callback)

    return True

def getLiveCamera():
    # print('getting live cam')
    current_scene = obs.obs_frontend_get_current_scene()
    currentScene = obs.obs_source_get_name(current_scene)
    # print(f'"{currentScene}" is live')
    # currentScene = obs.obs_scene_from_source(current_scene)
    for camera in cameras:
        # print(f'comparing against camera "{camera.name}" on scene "{camera.sceneName}"')
        if camera.sceneName == currentScene:
            return camera
    return None # TODO maybe throw an exception???

def transitionScene(cam):
    scenes = obs.obs_frontend_get_scenes()
    for scene in scenes:
        name = obs.obs_source_get_name(scene)
        if name == cam.sceneName:
            obs.obs_frontend_set_current_scene(scene)

# callbacks
# ---------

def configFileChanged_callback(props, prop, *args, **kwargs):
    # TODO hide all the camera controls and disconnect streamdeck until script is refreshed
    pass
    # print("(configfile update)")
    # configureMain()
    # print(f"there are {len(cameras)} cameras loaded")
    # clear scene pickers
    # p = obs.obs_properties_first(props)
    # while not p:
    #     if obs.obs_property_get_type(p) == obs.OBS_COMBO_TYPE_LIST:
    #         pname = obs.obs_property_name(p)
    #         obs.obs_properties_remove_by_name(props, pname)
    #     p = obs.obs_property_next(props)
    # # put new pickers in
    # scenes = obs.obs_frontend_get_scenes()
    # for camera in cameras:
    #     p = obs.obs_properties_add_list(props, f"picker_cam_{camera.name}", f'Cam: "{camera.name}"', obs.OBS_COMBO_TYPE_LIST, obs.OBS_COMBO_FORMAT_STRING)
    #     for scene in scenes:
    #         name = obs.obs_source_get_name(scene)
    #         obs.obs_property_list_add_string(p, name, name)
    # return props

def delayDurChanged_callback(props, prop, settings):
    global delayDur
    delayDur = obs.obs_data_get_int(settings, "picker_delay")
    print(f'delaydur is {delayDur}')

def callPreset_callback(preset: str) -> None:
    # TODO make sure preset exists
    print(f'calling preset "{preset}"')
    liveCam = getLiveCamera()
    if liveCam:
        print(f'"{liveCam.name}" is live')
    for i in range(len(cameras)): # TODO use selectedCameras here instead
        print(f'camera {i} {("is not", "is")[cameras[i] == liveCam]} live cam')
        if cameras[i] != liveCam:
            try:
                print(f'getting "{preset}" from {loadedConfig.Cameras[i].Assignments}')
                pos = getattr(loadedConfig.Cameras[i].Assignments, preset)
            except AttributeError:
                print(f'attribute does not exist')
                return False
            result = cameras[i].moveToPoint(pos.pan, pos.tilt, pos.zoom)
            print(f'camera move {"success" if result else "failed"}')
            time.sleep(delayDur / 1000)
            transitionScene(cameras[i])
            return True
    return False

def callScene_callback(page: str):
    global otherScenes
    scenes = obs.obs_frontend_get_scenes()
    for scene in scenes:
        name = obs.obs_source_get_name(scene)
        if name == otherScenes[page]:
            obs.obs_frontend_set_current_scene(scene)

def toggleStream_callback() -> bool:
    if not obs.obs_frontend_streaming_active():
        obs.obs_frontend_streaming_start()
        print('starting stream')
        # obs.obs_frontend_recording_start()
        return True
    else:
        obs.obs_frontend_streaming_stop()
        print('stopping stream')
        # obs.obs_frontend_recording_stop()
        return False

# def testNearButton_callback(props, prop):
#     print("dbg hit near")
#     callPreset_callback("altar")

# def testFarButton_callback(props, prop):
#     print("dbg hit far")
#     callPreset_callback("wide")
