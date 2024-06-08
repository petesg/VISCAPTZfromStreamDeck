import os
import threading
import ptz

from __time import curMillis

from PIL import Image, ImageDraw, ImageFont
from typing import List, Callable, Any
from StreamDeck.DeviceManager import DeviceManager
from StreamDeck.ImageHelpers import PILHelper
from StreamDeck.Devices.StreamDeck import StreamDeck

# DEBUG imports
import json
from types import SimpleNamespace

class ViscaDeck:

    _deck: StreamDeck
    _loadedConfig: SimpleNamespace
    _currentPage: str = 'HOME'
    _lastPage: str
    _callPreset_delegate: Callable[[str], None]
    _callImmediateScene_delegate: Callable[[str], None]
    _startStopStream_delegate: Callable[[bool], bool]
    _getStreamStatus_delegate: Callable[[None], bool]
    _keyHandlers: list[tuple[Callable[[bool, int, Any], None], Any]]
    _confirmPageHandler: Callable[[bool], None]
    _confirmPageContext: dict[str, Any] = {}
    _confirmPageMessage: str
    _selectedCams: list[str]
    _holdTimer: int = 0
    _camDriveSpeed: int = 1
    _drivenCamera: ptz.Camera = None
    _driveActive: bool = False
    _advDriveContext: Any
    _driveFinishedCallback: Callable
    _valueSelected: int = 0
    _availableValues: list[tuple[str, str]] = [
        ('icoBrightness_b.png', 'BRIGHTNESS'),
        ('icoAperture_b.png', 'APERTURE'),
        ('icoShutter_b.png', 'SHUTTER')
    ]
    
    def __init__(self, loadedConfig: SimpleNamespace, presetCallback: Callable[[str], None], sceneCallback: Callable[[str], None], getStreamCallback: Callable[[None], bool], streamCallback: Callable[[bool], bool]):
        print("-deck init")
        # print(loadedConfig)
        self._config = loadedConfig
        self._callPreset_delegate = presetCallback
        self._startStopStream_delegate = streamCallback
        self._getStreamStatus_delegate = getStreamCallback
        self._callImmediateScene_delegate = sceneCallback
        self._loadedConfig = loadedConfig
        self._selectedCams = ["foo", "bar"] # TODO implement this

        self._connectSurface()
    
    def close(self):
        self._disconnectSurface()

    def startAdvancedTransition(self, camera: ptz.Camera, position: object, finishedCallback: Callable, context: Any):
        self._drawDeck("DRIVE")
        self._advDriveContext = context
        self._drivenCamera = camera
        self._driveTarget = position
        self._driveFinishedCallback = finishedCallback

    def _connectSurface(self):
        streamdecks = DeviceManager().enumerate()

        print(f"Found {len(streamdecks)} Stream Deck(s).\n")
        if len(streamdecks) > 1:
            print('Warning: multiple streamdecks not [yet?] supported')

        for index, deck in enumerate(streamdecks):
            # Skip decks with no screen
            if not deck.is_visual():
                continue

            self._deck = deck
            break # TODO support picking from multiple decks

        self._deck.open()
        self._deck.reset()

        print(f"Opened '{self._deck.deck_type()}' device (serial number: '{self._deck.get_serial_number()}', fw: '{self._deck.get_firmware_version()}')")

        # Set initial screen brightness to 30%.
        self._deck.set_brightness(30)

        # Register callback function for when a key state changes.
        self._deck.set_key_callback(self._globalKeyPressed_callback)

        # Initialize handler list
        self._keyHandlers = [(None, None)] * self._deck.key_count()

        # Set initial key images.
        self._drawDeck("HOME")
        # for key in range(self._deck.key_count()):
        #     # TODO set key icons for home page
        #     pass
    
    def _disconnectSurface(self):
        # TODO close some threads or something?
        print('closing deck...')
        if self._deck:
            self._deck.close() # TODO this is still somehow leaving some threads hanging
        # block until threads are all gone
        for t in threading.enumerate():
            try:
                t.join()
            except RuntimeError:
                pass
        print('now safe to exit')
        self._deck = None
    
    def _drawDeck(self, page):
        # clear keys
        for i in range(self._deck.key_count()):
            self._keyHandlers[i] = (None, None)
            self._renderIcon(None, None, None, i)
        if page == "HOME":
            # populate preset buttons
            i = 0
            for p in list(self._loadedConfig.Presets.__dict__):
                if (i + 1) % self._deck.KEY_COLS == 0:
                    i += 1
                details = self._loadedConfig.Presets.__dict__[p]
                self._renderIcon(details.icon, details.label, None, i)
                self._keyHandlers[i] = (self._presetKeyPressed_callback, p)
                i += 1
            # non-preset transition button
            if (i + 1) % self._deck.KEY_COLS == 0:
                i += 1
            details = self._loadedConfig.Presets.__dict__[p]
            self._renderIcon("icoSwap.png", "SWAP", None, i)
            self._keyHandlers[i] = (self._presetKeyPressed_callback, None)
            i += 1
            # populate non-camera scene buttons
            for p in list(self._loadedConfig.ExtraScenes.__dict__):
                if (i + 1) % self._deck.KEY_COLS == 0:
                    i += 1
                details = self._loadedConfig.ExtraScenes.__dict__[p]
                self._renderIcon(details.icon, details.label, None, i)
                self._keyHandlers[i] = (self._sceneKeyPressed_callback, p)
                i += 1
            # stream button
            i = self._deck.KEY_COLS - 1
            if self._getStreamStatus_delegate():
                self._renderIcon(None, "END\nSTREAM", 'green', i)
            else:
                self._renderIcon(None, "START\nSTREAM", 'red', i)
            self._keyHandlers[i] = (self._streamKeyPressed_callback, None)
            # camera button
            i = self._deck.key_count() - 1
            self._renderIcon("icoCamera.png", ', '.join(self._selectedCams), None, i)
            self._keyHandlers[i] = (self._camsKeyPressed_callback, None)
            # edit button
            # i = self._deck.KEY_COLS * 2 - 1
            # self._renderIcon("icoEdit.png", "", None, i)
            # self._keyHandlers[i] = (self._editPresetsPressed_callback, None)
        elif page == "DRIVE":
            # arrow keys
            i = self._getKeyId(1, 0)
            self._renderIcon('icoUpArrow.png', None, None, i)
            self._keyHandlers[i] = (self._moveCameraArrowPressed_callback, 'UP')
            i = self._getKeyId(0, 1)
            self._renderIcon('icoLeftArrow.png', None, None, i)
            self._keyHandlers[i] = (self._moveCameraArrowPressed_callback, 'LEFT')
            i = self._getKeyId(2, 1)
            self._renderIcon('icoRightArrow.png', None, None, i)
            self._keyHandlers[i] = (self._moveCameraArrowPressed_callback, 'RIGHT')
            i = self._getKeyId(1, 2)
            self._renderIcon('icoDownArrow.png', None, None, i)
            self._keyHandlers[i] = (self._moveCameraArrowPressed_callback, 'DOWN')
            # zoom keys
            i = self._getKeyId(0, 0)
            self._renderIcon('icoZoomIn.png', None, None, i)
            self._keyHandlers[i] = (self._moveCameraZoomPressed_callback, 'IN')
            i = self._getKeyId(0, 2)
            self._renderIcon('icoZoomOut.png', None, None, i)
            self._keyHandlers[i] = (self._moveCameraZoomPressed_callback, 'OUT')
            # plus/minus keys
            i = self._getKeyId(2, 0)
            self._renderIcon('icoValueUp_b.png', None, None, i)
            self._keyHandlers[i] = (self._moveCameraValueUpDownPressed_callback, True)
            i = self._getKeyId(2, 2)
            self._renderIcon('icoValueDown_b.png', None, None, i)
            self._keyHandlers[i] = (self._moveCameraValueUpDownPressed_callback, False)
            # value select keys
            for j in range(min(3, len(self._availableValues))):
                i = self._getKeyId(3, j)
                self._renderIcon(self._availableValues[j][0], None, '#4AA1FF' if self._valueSelected == j else None, i) # or 4AA1FF instead of white
                self._keyHandlers[i] = (self._moveCameraSelectValuePressed_callback, j)
            # reset key
            i = self._getKeyId(1, 1)
            self._renderIcon('icoReset_r.png', None, None, i)
            self._keyHandlers[i] = (self._moveCameraResetPressed_callback, None)
            # submit/cancel keys
            i = self._getKeyId(4, 0)
            self._renderIcon('icoCheck_g.png', None, None, i)
            self._keyHandlers[i] = (self._moveCameraSubmitPressed_callback, None)
            i = self._getKeyId(4, 1)
            self._renderIcon('icoBack_r.png', None, None, i)
            self._keyHandlers[i] = (self._moveCameraCancelPressed_callback, None)
            # speed keys
            # for j in range(3):
                # i = self._getKeyId(0, j)
                # self._renderIcon(f'icoSpeed{j}.png', None, 'white' if j == self._camDriveSpeed else None, i)
                # self._keyHandlers[i] = (self._moveCameraSpeedPressed_callback, j)
            i = self._getKeyId(4, 2)
            self._renderIcon(f'icoSpeed{self._camDriveSpeed}.png', None, None, i)
            self._keyHandlers[i] = (self._moveCameraSpeedPressed_callback, None)
        elif page == "CONFIRM":
            # message
            self._renderLargeText(self._confirmPageMessage, 0, 0, 5, 1, 32, kerf=10)
            # yes key
            i = self._getKeyId(1, 1)
            self._renderIcon('icoCheck_g.png', None, None, i)
            self._keyHandlers[i] = (self._confirmHandler, True)
            # no key
            i = self._getKeyId(3, 1)
            self._renderIcon('icoCancel_r.png', None, None, i)
            self._keyHandlers[i] = (self._confirmHandler, False)
        else:
            # TODO error, bad page name
            pass
        self._lastPage = self._currentPage
        self._currentPage = page

    def _renderIcon(self, iconFile: str, label: str, borderColor: str, key: int) -> None:
        # resize icon file
        if iconFile:
            icon = Image.open(os.path.join(self._loadedConfig.AssetsPath, iconFile))
        else:
            icon = Image.new("RGB", (100,100), "black")
        image = PILHelper.create_scaled_image(self._deck, icon)

        # add border
        if borderColor:
            border = Image.new("RGBA", image.size, '#00000000')
            ovDraw = ImageDraw.Draw(border)
            ovDraw.rounded_rectangle((1, 1, image.width - 1, image.height - 1), 7, '#00000000', borderColor, 4)
            image = Image.alpha_composite(image.convert('RGBA'), border).convert('RGB')
        
        draw = ImageDraw.Draw(image)

        # add label
        if label:
            # wrap text
            font = ImageFont.truetype(os.path.join(self._loadedConfig.AssetsPath, 'ariblk.ttf'), 12 if iconFile else 16)
            lines = label.split('\n')
            temp = ''
            while draw.textlength(lines[-1], font) >= image.width:
                splindex = lines[-1].rfind(' ')
                if splindex < 0:
                    break # TODO make this restart the whole deal with a smaller font size instead of just giving up
                temp = lines[-1][splindex:] + temp
                lines[-1] = lines[-1][:splindex]
                if draw.textlength(lines[-1], font) < image.width:
                    lines.append(temp[1:])
            # overlay text
            draw.multiline_text((image.width / 2, 6 if iconFile else 36), '\n'.join(lines), 'white', font, "ma" if iconFile else "mm")

        self._deck.set_key_image(key, PILHelper.to_native_format(self._deck, image))
    
    def _renderLargeText(self, text:str, col:int, row:int, cols:int, rows:int, fontHt:float, textColor:str='white', backColor:str='black', kerf:int=0):
        # clamp bounds to available area
        if col + cols > self._deck.KEY_COLS:
            cols = self._deck.KEY_COLS - col
        if row + rows > self._deck.KEY_ROWS:
            rows = self._deck.KEY_ROWS - row

        # create empty image of the correct size and draw the text
        canvasWd = self._deck.KEY_PIXEL_WIDTH * cols + kerf * (cols - 1)
        canvasHt = self._deck.KEY_PIXEL_HEIGHT * rows + kerf * (rows - 1)
        rawImg = Image.new("RGB", (canvasWd, canvasHt), backColor)
        draw = ImageDraw.Draw(rawImg)
        font = ImageFont.truetype(os.path.join(self._loadedConfig.AssetsPath, 'ariblk.ttf'), fontHt)
        draw.text((canvasWd / 2, canvasHt / 2), text, font=font, anchor='mm', align='center', stroke_fill=textColor)

        # chop into tiles and assign to keys
        for j in range(rows):
            for i in range(cols):
                key = self._getKeyId(i, j)
                x1 = i * (self._deck.KEY_PIXEL_WIDTH + kerf)
                y1 = j * (self._deck.KEY_PIXEL_HEIGHT + kerf)
                x2 = x1 + self._deck.KEY_PIXEL_WIDTH
                y2 = y1 + self._deck.KEY_PIXEL_HEIGHT
                tile = draw._image.crop((x1, y1, x2, y2))
                self._deck.set_key_image(key, PILHelper.to_native_format(self._deck, tile))

    def _getKeyId(self, col: int, row: int):
        if col >= self._deck.KEY_COLS:
            raise IndexError('Key column out of range')
        elif row >= self._deck.KEY_ROWS:
            raise IndexError('Key row out of range')
        return self._deck.KEY_COLS * row + col

    def _exitAdvancedTransition(self):
        self._driveFinishedCallback = None
        self._drivenCamera = None
        self._driveTarget = None
        self._advDriveContext = None
        self._driveActive = False
        self._drawDeck("HOME")
    
    def _startStopStream(self, state: bool, key: int, confirmed: bool) -> None:
        if not state:
            return
        if confirmed:
            startStream = self._confirmPageContext['STREAM']
            self._startStopStream_delegate(startStream)
        self._drawDeck('HOME')

    def _camsKeyPressed_callback(self, state: bool, key: int, context: Any) -> None:
        # TODO
        pass

    def _editPresetsPressed_callback(self, state: bool, key: int, context: Any) -> None:
        # TODO
        pass

    def _streamKeyPressed_callback(self, state: bool, key: int, context: Any) -> None:
        if state:
            streamIsOn = self._getStreamStatus_delegate()
            self._confirmPageContext['STREAM'] = not streamIsOn
            self._confirmHandler = self._startStopStream
            self._confirmPageMessage = ('STOP' if streamIsOn else 'START') + "     STREAM?"
            self._drawDeck('CONFIRM')
        #     if not self._holdTimer:
        #         self._holdTimer = curMillis() + 2000
        #         # TODO render intermediate border color
        #     return
        # if not state and self._holdTimer and curMillis() > self._holdTimer:
            # print('stream button pressed')
            # if self._startStopStream():
            #     self._renderIcon(None, "END\nSTREAM", 'green', key)
            # else:
            #     self._renderIcon(None, "START\nSTREAM", 'red', key)
            # self._holdTimer = 0

    def _presetKeyPressed_callback(self, state: bool, key: int, preset: str) -> None:
        print(f'KEY CALLBACK')
        if not state:
            return
        print(f'PRESSED')
        # TODO don't do anything if a preset is already being called (does that already take care of itself bc we're not using asynch callback and this blocks?)
        p = None
        if preset:
            p = getattr(self._loadedConfig.Presets, preset)
            print(f'RENDER rendering {key} as stdby')
        self._renderIcon(p.icon if p else "icoSwap.png", p.label if p else "SWAP", 'red', key)
        self._callPreset_delegate(preset)
        # TODO move delay here (wait, why again?)
        if self._currentPage == "HOME":
            self._renderIcon(p.icon if p else "icoSwap.png", p.label if p else "SWAP", None, key)
            print(f'RENDER rendering {key} normal')
        # TODO save what preset is being viewed so it can be re-highlighted if the deck is redrawn

    def _sceneKeyPressed_callback(self, state: bool, key: int, scene: str) -> None:
        if not state:
            return
        self._callImmediateScene_delegate(scene)

    def _globalKeyPressed_callback(self, deck, key, state):
        (handler, context) = self._keyHandlers[key]
        if handler:
            handler(state, key, context)
        pass

    
    def _moveCameraSelectValuePressed_callback(self, pressed: bool, key: int, selection: int):
        if not pressed:
            return
        self._valueSelected = selection
        for j in range(min(3, len(self._availableValues))):
            i = self._getKeyId(3, j)
            self._renderIcon(self._availableValues[j][0], None, '#4AA1FF' if self._valueSelected == j else None, i) # or 4AA1FF instead of white

    def _moveCameraArrowPressed_callback(self, pressed: bool, key: int, dir: str):
        pspeed = [0x01, 0x0A, 0x18][self._camDriveSpeed]
        tspeed = [0x01, 0x08, 0x14][self._camDriveSpeed]
        # TODO keep matrix of pressed direction buttons to support multi-key inputs
        if not pressed:
            if self._driveActive:
                pspeed = 0
                tspeed = 0
            else:
                # button is just getting released from key press to go into drive mode
                return
        print(f'DRIVE {dir}')
        if dir == 'UP':
            pspeed = 0
        elif dir == 'DOWN':
            pspeed = 0
            tspeed = -tspeed
        elif dir == 'LEFT':
            pspeed = -pspeed
            tspeed = 0
        elif dir == 'RIGHT':
            tspeed = 0
        else:
            raise ValueError(f'Invalid pan/tilt direction: "{dir}"')
        self._drivenCamera.drivePanTilt(pspeed, tspeed)
        self._driveActive = True

    def _moveCameraZoomPressed_callback(self, pressed: bool, key: int, dir: str):
        speed = [1, 3, 7][self._camDriveSpeed]
        if not pressed:
            if self._driveActive:
                speed = 0
            else:
                # button is just getting released from key press to go into drive mode
                return
        elif dir == 'IN':
            pass
        elif dir == 'OUT':
            speed *= -1
        else:
            raise ValueError(f'Invalid zoom direction: "{dir}"')
        self._drivenCamera.driveZoom(speed)
        self._driveActive = True

    def _moveCameraValueUpDownPressed_callback(self, pressed: bool, key: int, up: bool):
        if not pressed:
            return
        if self._availableValues[self._valueSelected][1] == "BRIGHTNESS":
            # TODO
            # print(('increasing' if up else 'decreasing') + ' brightness')
            self._drivenCamera.driveBrightness(up)
        elif self._availableValues[self._valueSelected][1] == "SHUTTER":
            # TODO
            # print(('increasing' if up else 'decreasing') + ' shutter speed')
            self._drivenCamera.driveShutter(up)
        elif self._availableValues[self._valueSelected][1] == "APERTURE":
            # TODO
            # print(('increasing' if up else 'decreasing') + ' aperture')
            self._drivenCamera.driveAperture(up)

    def _moveCameraResetPressed_callback(self, pressed: bool, key: int, context: Any):
        if pressed and self._driveTarget:
            self._drivenCamera.moveToPoint(self._driveTarget.pan, self._driveTarget.tilt, self._driveTarget.zoom)

    def _moveCameraSubmitPressed_callback(self, pressed: bool, key: int, context: Any):
        if not pressed:
            return
        self._drivenCamera.driveZoom(0)
        self._drivenCamera.drivePanTilt(0, 0)
        self._driveFinishedCallback(self._advDriveContext)
        self._exitAdvancedTransition()

    def _moveCameraCancelPressed_callback(self, pressed: bool, key: int, context: Any):
        if not pressed:
            return
        self._drivenCamera.driveZoom(0)
        self._drivenCamera.drivePanTilt(0, 0)
        self._exitAdvancedTransition()

    def _moveCameraSpeedPressed_callback(self, pressed: bool, key: int, context: Any):
        if not pressed:
            return
        self._camDriveSpeed += 1
        self._camDriveSpeed %= 3
        self._renderIcon(f'icoSpeed{self._camDriveSpeed}.png', None, None, self._getKeyId(4, 2))
        # for j in range(3):
        #     i = self._getKeyId(0, j)
        #     self._renderIcon(f'icoSpeed{j}.png', None, 'white' if key == i else None, i)
        # self._camDriveSpeed = speed

# EXAMPLE CODE
# ------------


# # Folder location of image assets used by this example.
# ASSETS_PATH = os.path.join(os.path.dirname(__file__), "examples\\Assets")

# # Generates a custom tile with run-time generated text and custom image via the
# # PIL module.
# def render_key_image(deck, icon_filename, font_filename, label_text):
#     # Resize the source image asset to best-fit the dimensions of a single key,
#     # leaving a margin at the bottom so that we can draw the key title
#     # afterwards.
#     icon = Image.open(icon_filename)
#     image = PILHelper.create_scaled_image(deck, icon, margins=[0, 0, 20, 0])

#     # Load a custom TrueType font and use it to overlay the key index, draw key
#     # label onto the image a few pixels from the bottom of the key.
#     draw = ImageDraw.Draw(image)
#     font = ImageFont.truetype(font_filename, 14)
#     draw.text((image.width / 2, image.height - 5), text=label_text, font=font, anchor="ms", fill="white")

#     return PILHelper.to_native_format(deck, image)


# # Returns styling information for a key based on its position and state.
# def get_key_style(deck, key, state):
#     # Last button in the example application is the exit button.
#     exit_key_index = deck.key_count() - 1

#     if key == exit_key_index:
#         name = "exit"
#         icon = "{}.png".format("Exit")
#         font = "Roboto-Regular.ttf"
#         label = "Bye" if state else "Exit"
#     else:
#         name = "emoji"
#         icon = "{}.png".format("Pressed" if state else "Released")
#         font = "Roboto-Regular.ttf"
#         label = "Pressed!" if state else f"Key {key}"

#     return {
#         "name": name,
#         "icon": os.path.join(ASSETS_PATH, icon),
#         "font": os.path.join(ASSETS_PATH, font),
#         "label": label
#     }


# # Creates a new key image based on the key index, style and current key state
# # and updates the image on the StreamDeck.
# def update_key_image(deck, key, state):
#     # Determine what icon and label to use on the generated key.
#     key_style = get_key_style(deck, key, state)

#     # Generate the custom key with the requested image and label.
#     image = render_key_image(deck, key_style["icon"], key_style["font"], key_style["label"])

#     # Use a scoped-with on the deck to ensure we're the only thread using it
#     # right now.
#     with deck:
#         # Update requested key with the generated image.
#         deck.set_key_image(key, image)


# # Prints key state change information, updates rhe key image and performs any
# # associated actions when a key is pressed.
# def key_change_callback(deck, key, state):
#     # Print new key state
#     # print("Deck {} Key {} = {}".format(deck.id(), key, state), flush=True)
#     print(f"Key {key} = {state}", flush=True)

#     # Update the key image based on the new key state.
#     update_key_image(deck, key, state)

#     # Check if the key is changing to the pressed state.
#     if state:
#         key_style = get_key_style(deck, key, state)

#         # When an exit button is pressed, close the application.
#         if key_style["name"] == "exit":
#             # Use a scoped-with on the deck to ensure we're the only thread
#             # using it right now.
#             with deck:
#                 # Reset deck, clearing all button images.
#                 deck.reset()

#                 # Close deck handle, terminating internal worker threads.
#                 deck.close()

#                 print("EXIT")

def dbgPresetHandlerNoOp(preset: str):
    return

if __name__ == "__main__":

    with open("config.json") as configFile:
        jsonData = configFile.read()
    loadedConfig = json.loads(jsonData, object_hook=lambda d: SimpleNamespace(**d))
    deck = ViscaDeck(loadedConfig, dbgPresetHandlerNoOp)

    # streamdecks = DeviceManager().enumerate()

    # print("Found {} Stream Deck(s).\n".format(len(streamdecks)))

    # for index, deck in enumerate(streamdecks):
    #     # This example only works with devices that have screens.
    #     if not deck.is_visual():
    #         continue

    #     deck.open()
    #     deck.reset()

    #     print("Opened '{}' device (serial number: '{}', fw: '{}')".format(
    #         deck.deck_type(), deck.get_serial_number(), deck.get_firmware_version()
    #     ))

    #     # Set initial screen brightness to 30%.
    #     deck.set_brightness(30)

    #     # Set initial key images.
    #     for key in range(deck.key_count()):
    #         update_key_image(deck, key, False)

    #     # Register callback function for when a key state changes.
    #     deck.set_key_callback(key_change_callback)

    #     with open('config.json') as configFile:
    #         jsonData = configFile.read()
    #     loadedConfig = json.loads(jsonData, object_hook=lambda d: SimpleNamespace(**d))

    #     # d = ViscaDeck(loadedConfig, None)
    #     # d.connectStreamDeck()

    #     # Wait until all application threads have terminated (for this example,
    #     # this is when all deck handles are closed).
    #     for t in threading.enumerate():
    #         try:
    #             t.join()
    #         except RuntimeError:
    #             pass

    #     deck.disconnectStreamDeck()
