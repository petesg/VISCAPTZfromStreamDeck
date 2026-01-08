import os
import threading
import ptz
import time

from __time import curMillis

from PIL import Image, ImageDraw, ImageFont
from typing import List, Callable, Any, Literal
from StreamDeck.DeviceManager import DeviceManager
from StreamDeck.ImageHelpers import PILHelper
from StreamDeck.Devices.StreamDeck import StreamDeck

# DEBUG imports
import json
from types import SimpleNamespace

class ObsDeckEvents:
    callPreset: Callable[[str, ptz.Camera], None]
    callImmediateScene: Callable[[str], None]
    startStopStream: Callable[[bool], bool]
    getStreamStatus: Callable[[None], bool]
    getFreeCameras: Callable[[None], list[ptz.Camera]]
    setPreviewCamera: Callable[[ptz.Camera], None]

class ViscaDeck:

    _deck: StreamDeck
    _loadedConfig: SimpleNamespace
    _deckSize: Literal['REGULAR', 'XL']
    _currentPage: str = 'HOME'
    _lastPage: str
    # _obs.callPreset: Callable[[str], None]
    # _obs.callImmediateScene: Callable[[str], None]
    # _obs.startStopStream: Callable[[bool], bool]
    # _obs.getStreamStatus: Callable[[None], bool]
    _obs: ObsDeckEvents
    _keyHandlers: list[tuple[Callable[[bool, int, Any], None], Any]]
    _confirmPageHandler: Callable[[bool], None]
    _confirmPageContext: dict[str, Any] = {}
    _confirmPageMessage: str
    _selectedCam: ptz.Camera = None # TODO this will cause problems if you try to do something before selecting a camera, needs to get fixed by having script_update() set this the first time it runs
    _holdTimer: int = 0
    _camDriveSpeed: int = 1
    _drivenCamera: ptz.Camera = None
    _driveActive: bool = False
    _advDriveContext: Any
    _driveFinishedCallback: Callable
    _valueSelected: int = 0
    _availableValues: list[tuple[str, str, float]] = [
        ['icoAperture_b.png', 'APERTURE', 0],
        ['icoShutter_b.png', 'SHUTTER', 0]
    ]
    _iconCache: dict[str, Image.Image] = {}
    
    def __init__(self, loadedConfig: SimpleNamespace, callbacks: ObsDeckEvents): #presetCallback: Callable[[str], None], sceneCallback: Callable[[str], None], getStreamCallback: Callable[[None], bool], streamCallback: Callable[[bool], bool]):
        print("-deck init")
        # print(loadedConfig)
        self._config = loadedConfig
        # self._obs.callPreset = presetCallback
        # self._obs.startStopStream = streamCallback
        # self._obs.getStreamStatus = getStreamCallback
        # self._obs.callImmediateScene = sceneCallback
        self._obs = callbacks
        self._loadedConfig = loadedConfig
        # self._selectedCams = ["foo", "bar"] # TODO implement this

        self._connectSurface()
    
    def open(self):
        if self._deckSize == 'XL':
            self._obs.callPreset(None, self._selectedCam) # TODO may select live camera because at the time this is run currently, obs_frontend_get_current_scene returns none for some reason
            self._drawDeck('HOME')

    def close(self):
        self._disconnectSurface()

    def startAdvancedTransition(self, camera: ptz.Camera, position: Any, finishedCallback: Callable, context: Any):
        if self._deckSize == 'REGULAR':
            self._drawDeck("DRIVE")
        self._advDriveContext = context
        self._drivenCamera = camera
        self._driveTarget = position
        self._driveFinishedCallback = finishedCallback
        # print(f'STARTED ADV. TRANSITION FOR CAMERA {camera.name} to POS. {position} W/ CONTEXT {context}')
    
    def setSelectedCamera(self, cam: ptz.Camera) -> None:
        # print(f'SELECTED CAM CHANGED BY OBS TO {cam.name}')
        if cam is None:
            # TODO handle this
            return
        if self._deckSize == 'XL':
            self._camSelectPressed_callback(True, None, cam)
            self._obs.callPreset(None, cam)
        else:
            self._selectedCam = cam

    def _connectSurface(self):
        streamdecks = DeviceManager().enumerate()

        print(f"Found {len(streamdecks)} Stream Deck(s).\n")
        if len(streamdecks) > 1:
            print('Warning: multiple streamdecks not [yet?] supported')

        for _, deck in enumerate(streamdecks):
            # Skip decks with no screen
            if not deck.is_visual():
                continue

            self._deck = deck
            break # TODO support picking from multiple decks

        self._deck.open()
        self._deck.reset()

        if self._deck.KEY_COLS == 8 and self._deck.KEY_ROWS == 4:
            self._deckSize = 'XL'
        else:
            self._deckSize = 'REGULAR' # only sizes I've bothered to support so far

        print(f"Opened '{self._deck.deck_type()}' device (serial number: '{self._deck.get_serial_number()}', fw: '{self._deck.get_firmware_version()}')")

        # Set initial screen brightness to 30%.
        self._deck.set_brightness(30)

        # Register callback function for when a key state changes.
        self._deck.set_key_callback(self._globalKeyPressed_callback)

        # Initialize handler list
        self._keyHandlers = [(None, None)] * self._deck.key_count()

        # Default the selected camera to something
        self._selectedCam = self._obs.getFreeCameras()[0]

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
    
    def _keyRow(self, keyIndex: int) -> int:
        return int(keyIndex / self._deck.KEY_COLS)
    
    def _keyCol(self, keyIndex: int) -> int:
        return keyIndex % self._deck.KEY_COLS

    def _keyIndex(self, col: int, row: int):
        if col >= self._deck.KEY_COLS:
            raise IndexError('Key column out of range')
        elif row >= self._deck.KEY_ROWS:
            raise IndexError('Key row out of range')
        return self._deck.KEY_COLS * row + col

    # TODO this needs to be profiled, it takes forever to run
    def _drawSceneButtons(self, beginCol: int, endCol: int | None, beginRow: int, endRow: int | None, sceneType: Literal['CAM_PRESET', 'TITLE_CARD'], startButton: int = None) -> int | None:
        # calculate auto begin/end
        if endCol is None:
            endCol = self._deck.KEY_COLS - 1
        if endRow is None:
            endRow = self._deck.KEY_ROWS - 1
        # initialize button index
        i = beginCol + beginRow * self._deck.KEY_COLS
        if startButton is not None and \
                self._keyCol(startButton) >= beginCol and \
                self._keyCol(startButton) <= endCol and \
                self._keyRow(startButton) >= beginRow and \
                self._keyRow(startButton) <= endRow:
            i = startButton
        # print(f'drawing {sceneType} scene buttons starting at key {i}')
        # populate buttons
        if sceneType == 'CAM_PRESET':
            scenes = self._loadedConfig.Presets.__dict__
        elif sceneType == 'TITLE_CARD':
            scenes = self._loadedConfig.ExtraScenes.__dict__
        # tf = time.time()
        for p in list(scenes):
            # t0 = time.time()
            # print(f'drawing scene button on key {i}')
            if self._keyRow(i) > endRow:
                return None
            # t1 = time.time()
            # set up key
            if sceneType == 'CAM_PRESET':
                self._keyHandlers[i] = (self._presetKeyPressed_callback, p)
            elif sceneType == 'TITLE_CARD':
                self._keyHandlers[i] = (self._sceneKeyPressed_callback, p)
            # t2 = time.time()
            details = scenes[p]
            self._renderIcon(details.icon, details.label, None, i)
            # t3 = time.time()
            # increment to next key and roll over if needed
            if self._keyCol(i) == endCol:
                i = self._keyIndex(beginCol, self._keyRow(i) + 1)
            else:
                i += 1
            # t4 = time.time()
            # print(f'"{p}" - loop: {t0 - tf}, ovf ck: {t1 - t0}, presets load: {t2 - t1}, render: {t3 - t2}, step: {t4 -t3}')
            # tf = time.time()
        return i

    def _drawDriveButtons(self, col: int, row: int):
        if self._deckSize == 'XL':
            square = True
        else:
            square = False
        # arrow keys
        i = self._keyIndex(col + 1, row + 0)
        self._renderIcon('icoUpArrow.png', None, None, i)
        self._keyHandlers[i] = (self._moveCameraArrowPressed_callback, 'UP')
        i = self._keyIndex(col + 0, row + 1)
        self._renderIcon('icoLeftArrow.png', None, None, i)
        self._keyHandlers[i] = (self._moveCameraArrowPressed_callback, 'LEFT')
        i = self._keyIndex(col + 2, row + 1)
        self._renderIcon('icoRightArrow.png', None, None, i)
        self._keyHandlers[i] = (self._moveCameraArrowPressed_callback, 'RIGHT')
        i = self._keyIndex(col + 1, row + 2)
        self._renderIcon('icoDownArrow.png', None, None, i)
        self._keyHandlers[i] = (self._moveCameraArrowPressed_callback, 'DOWN')
        # zoom keys
        i = self._keyIndex(col + 0, row + 0)
        self._renderIcon('icoZoomIn.png', None, None, i)
        self._keyHandlers[i] = (self._moveCameraZoomPressed_callback, 'IN')
        i = self._keyIndex(col + 0, row + 2)
        self._renderIcon('icoZoomOut.png', None, None, i)
        self._keyHandlers[i] = (self._moveCameraZoomPressed_callback, 'OUT')
        # plus/minus keys
        i = self._keyIndex(col + 2, row + 0)
        self._renderIcon('icoValueUp_b.png', None, None, i)
        self._keyHandlers[i] = (self._moveCameraValueUpDownPressed_callback, True)
        i = self._keyIndex(col + 2, row + 2)
        self._renderIcon('icoValueDown_b.png', None, None, i)
        self._keyHandlers[i] = (self._moveCameraValueUpDownPressed_callback, False)
        # autofocus key
        if square:
            i = self._keyIndex(col, row + 3)
        else:
            i = self._keyIndex(col + 3, row)
        self._renderIcon('icoAutofocus_b.png', None, None, i)
        self._keyHandlers[i] = (self._moveCameraAutofocusPressed_callback, None)
        # value select keys
        for j in range(min(2 if square else 3, len(self._availableValues))):
            if square:
                i = self._keyIndex(col + j + 1, row + 3)
            else:
                i = self._keyIndex(col + 3, row + j + 1)
            self._renderIcon(self._availableValues[j][0], None, '#4AA1FF' if self._valueSelected == j else None, i, '#4AA1FF7F', self._availableValues[j][2]) # or 4AA1FF instead of white
            self._keyHandlers[i] = (self._moveCameraSelectValuePressed_callback, j)
        # reset key
        i = self._keyIndex(col + 1, row + 1)
        self._renderIcon('icoReset_r.png', None, None, i)
        self._keyHandlers[i] = (self._moveCameraResetPressed_callback, None)
        # submit/cancel keys
        i = self._keyIndex(col + (3 if square else 4), row + 0)
        self._renderIcon('icoCheck_g.png', None, None, i)
        self._keyHandlers[i] = (self._moveCameraSubmitPressed_callback, None)
        if self._deckSize != 'XL': # no cancel button for xl
            i = self._keyIndex(col + (3 if square else 4), row + 1)
            self._renderIcon('icoBack_r.png', None, None, i)
            self._keyHandlers[i] = (self._moveCameraCancelPressed_callback, None)
        # speed key
        i = self._keyIndex(col + (3 if square else 4), row + (1 if square else 2))
        self._renderIcon(f'icoSpeed{self._camDriveSpeed}.png', None, None, i)
        self._keyHandlers[i] = (self._moveCameraSpeedPressed_callback, None)

    def _drawDeck(self, page):
        # clear keys
        for i in range(self._deck.key_count()):
            self._keyHandlers[i] = (None, None)
            self._renderIcon(None, None, None, i)
        if page == "HOME":
            if self._deckSize == 'REGULAR':
                # populate preset buttons
                i = self._drawSceneButtons(0, 3, 0, 2, 'CAM_PRESET')
                # non-preset transition button
                if (i + 1) % self._deck.KEY_COLS == 0:
                    i += 1
                self._renderIcon("icoMove.png", "MOVE", None, i)
                self._keyHandlers[i] = (self._presetKeyPressed_callback, None)
                i += 1
                if (i + 1) % self._deck.KEY_COLS == 0:
                    i += 1
                # populate non-camera scene buttons
                self._drawSceneButtons(0, 3, 0, 2, 'TITLE_CARD', i)
            elif self._deckSize == 'XL':
                i = self._drawSceneButtons(4, 7, 0, 2, 'CAM_PRESET')
                i = self._drawSceneButtons(4, 7, 0, 2, 'TITLE_CARD', i)
            # stream button
            if self._deckSize == 'REGULAR':
                i = self._deck.KEY_COLS - 1
            elif self._deckSize == 'XL':
                i = self._keyIndex(3, 2)
            if self._obs.getStreamStatus():
                self._renderIcon(None, "END\nSTREAM", 'green', i)
            else:
                self._renderIcon(None, "START\nSTREAM", 'red', i)
            self._keyHandlers[i] = (self._streamKeyPressed_callback, None)
            # camera button[s]
            if self._deckSize == 'REGULAR':
                i = self._deck.key_count() - 1
                self._renderIcon("icoSwap.png", 'CAM SEL', None, i) # self._selectedCam.name.upper()
                self._keyHandlers[i] = (self._camsKeyPressed_callback, None)
            elif self._deckSize == 'XL':
                availableCams = self._obs.getFreeCameras()
                j = 4
                for camName in [c.name for c in self._loadedConfig.Cameras]:
                    callback = None
                    cam = None
                    for c in availableCams:
                        if c.name == camName:
                            callback = self._camSelectPressed_callback
                            cam = c
                            break
                    i = self._keyIndex(j, 3)
                    self._renderIcon('icoCamera.png' if cam else 'icoCamera_g.png', camName.upper(), 'white' if cam == self._selectedCam else None, i)
                    self._keyHandlers[i] = (callback, cam)
                    j += 1
                    # drive panel on XL also
                    self._drawDriveButtons(0, 0)

        elif page == "DRIVE":
            self._drawDriveButtons(0, 0)

        elif page == "CONFIRM":
            # message
            self._renderLargeText(self._confirmPageMessage, 0, 0, 5, 1, 32, kerf=10)
            # yes key
            i = self._keyIndex(1, 1)
            self._renderIcon('icoCheck_g.png', None, None, i)
            self._keyHandlers[i] = (self._confirmHandler, True)
            # no key
            i = self._keyIndex(3, 1)
            self._renderIcon('icoCancel_r.png', None, None, i)
            self._keyHandlers[i] = (self._confirmHandler, False)

        elif page == 'CAMSELECT':
            # title
            self._renderLargeText('SELECT CAMERA', 0, 0, 5, 1, 32, kerf=10)
            # camera buttons
            availableCams = self._obs.getFreeCameras()
            j = 0
            for cam in availableCams:
                i = self._keyIndex(j, 1)
                self._renderIcon(None, cam.name, 'white' if cam == self._selectedCam else None, i)
                self._keyHandlers[i] = (self._camSelectPressed_callback, cam)
                j += 1
            # back button
            i = self._keyIndex(0, 2)
            self._renderIcon('icoBack.png', None, None, i)
            self._keyHandlers[i] = (self._goToPagePressed_callback, 'HOME')

        else:
            raise ValueError(f'Bad page name: "{page}".')

        if self._currentPage != page:
            self._lastPage = self._currentPage
        self._currentPage = page

    def _renderIcon(self, iconFile: str, label: str, borderColor: str, key: int, fillColor: str | None = None, fillPct: float = 1) -> None:
        # t0 = time.time()
        # see if scaled icon is cached already
        if not iconFile:
            image = PILHelper.create_image(self._deck, 'black')
        elif iconFile in self._iconCache.keys():
            image = self._iconCache[iconFile].copy()
            # t1 = time.time()
        else:
            # resize icon file
            # if iconFile:
            icon = Image.open(os.path.join(self._loadedConfig.AssetsPath, iconFile))
            # else:
                # icon = Image.new("RGB", (100,100), "black")
            # t1 = time.time()
            image = PILHelper.create_scaled_image(self._deck, icon)
            self._iconCache[iconFile] = image.copy()
        # t2 = time.time()

        # add value-indicating fill
        if fillColor is not None:
            overlay = Image.new('RGBA', image.size, '#00000000')
            ovDraw = ImageDraw.Draw(overlay)
            print(f'drawing {fillPct*100:.1f}% fill from (0, {(1 - fillPct) * image.height}) to ({image.width}, {image.height})')
            ovDraw.rectangle((0, (1 - fillPct) * image.height, image.width, image.height), fillColor, None)
            image = Image.alpha_composite(image.convert('RGBA'), overlay).convert('RGB')

        # add border
        if borderColor:
            border = Image.new("RGBA", image.size, '#00000000')
            ovDraw = ImageDraw.Draw(border)
            ovDraw.rounded_rectangle((1, 1, image.width - 1, image.height - 1), 9, "#00000000", borderColor, 4)
            image = Image.alpha_composite(image.convert('RGBA'), border).convert('RGB')
        # t3 = time.time()
        
        draw = ImageDraw.Draw(image)
        # t4 = time.time()

        # add label
        # t5 = t6 = time.time()
        if label:
            # wrap text
            font = ImageFont.truetype(os.path.join(self._loadedConfig.AssetsPath, 'ariblk.ttf'), 12 if iconFile else 16)
            lines = label.split('\n')
            temp = ''
            # t5 = time.time()
            while draw.textlength(lines[-1], font) >= image.width:
                splindex = lines[-1].rfind(' ')
                if splindex < 0:
                    break # TODO make this restart the whole deal with a smaller font size instead of just giving up
                temp = lines[-1][splindex:] + temp
                lines[-1] = lines[-1][:splindex]
                if draw.textlength(lines[-1], font) < image.width:
                    lines.append(temp[1:])
            # t6 = time.time()
            # overlay text
            draw.multiline_text((image.width / 2, 6 if iconFile else 36), '\n'.join(lines), 'white', font, "ma" if iconFile else "mm")
        # t7 = time.time()

        self._deck.set_key_image(key, PILHelper.to_native_format(self._deck, image))
        # t8 = time.time()

        # iden = label or iconFile or '<blank>'
        # print(f'DRAW {iden.ljust(18)} PROFILING - total: {t8 - t0:.3f}, icon fetch: {t1 - t0:.3f}, scaling: {t2 - t1:.3f}, border: {t3 - t2:.3f}, conversion: {t4 - t3:.3f}, font load: {t5 - t4:.3f}, text splitting: {t6 - t5:.3f}, title draw: {t7 - t6:.3f}, deck draw: {t8 - t7:.3f}')
    
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
                key = self._keyIndex(i, j)
                x1 = i * (self._deck.KEY_PIXEL_WIDTH + kerf)
                y1 = j * (self._deck.KEY_PIXEL_HEIGHT + kerf)
                x2 = x1 + self._deck.KEY_PIXEL_WIDTH
                y2 = y1 + self._deck.KEY_PIXEL_HEIGHT
                tile = draw._image.crop((x1, y1, x2, y2))
                self._deck.set_key_image(key, PILHelper.to_native_format(self._deck, tile))

    def _exitAdvancedTransition(self):
        if self._deckSize != 'XL':
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
            self._obs.startStopStream(startStream)
        self._drawDeck('HOME')

    def _camsKeyPressed_callback(self, state: bool, key: int, context: Any) -> None:
        self._drawDeck('CAMSELECT')
        pass

    def _editPresetsPressed_callback(self, state: bool, key: int, context: Any) -> None:
        # TODO
        pass

    def _streamKeyPressed_callback(self, state: bool, key: int, context: Any) -> None:
        if state:
            streamIsOn = self._obs.getStreamStatus()
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
        if not state:
            return
        # TODO don't do anything if a preset is already being called (does that already take care of itself bc we're not using asynch callback and this blocks?)
        p = None
        if preset:
            p = getattr(self._loadedConfig.Presets, preset)
            # print(f'RENDER rendering {key} as stdby')
        self._renderIcon(p.icon if p else "icoMove.png", p.label if p else "MOVE", 'red', key)
        self._obs.callPreset(preset, self._selectedCam)
        # TODO move delay here (wait, why again?)
        if self._currentPage == "HOME":
            self._renderIcon(p.icon if p else "icoMove.png", p.label if p else "MOVE", None, key)
            # print(f'RENDER rendering {key} normal')
        # TODO save what preset is being viewed so it can be re-highlighted if the deck is redrawn

    def _sceneKeyPressed_callback(self, state: bool, key: int, scene: str) -> None:
        if not state:
            return
        self._obs.callImmediateScene(scene)

    def _globalKeyPressed_callback(self, deck, key, state):
        (handler, context) = self._keyHandlers[key]
        if handler:
            handler(state, key, context)
        pass

    
    def _moveCameraSelectValuePressed_callback(self, pressed: bool, key: int, selection: int):
        if not pressed:
            return
        self._valueSelected = selection
        for j in range(min(4, len(self._availableValues))):
            if self._deckSize == 'REGULAR':
                i = self._keyIndex(3, j)
            elif self._deckSize == 'XL':
                i = self._keyIndex(j, 3)
            self._renderIcon(self._availableValues[j][0], None, '#4AA1FF' if self._valueSelected == j else None, i, '#4AA1FF7F', self._availableValues[j][2])

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
        # print(f'DRIVE {dir}')
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
        self._drivenCamera.lockFocus(False)
        self._drivenCamera.drivePanTilt(pspeed, tspeed)
        self._drivenCamera.lockFocus(True)
        self._driveActive = True

    def _moveCameraZoomPressed_callback(self, pressed: bool, key: int, dir: str):
        speed = [1, 4, 7][self._camDriveSpeed]
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
        self._drivenCamera.lockFocus(False)
        self._drivenCamera.driveZoom(speed)
        self._drivenCamera.lockFocus(True)
        self._driveActive = True

    def _moveCameraValueUpDownPressed_callback(self, pressed: bool, key: int, up: bool):
        if not pressed:
            return
        if self._availableValues[self._valueSelected][1] == "BRIGHTNESS":
            # TODO
            # print(('increasing' if up else 'decreasing') + ' brightness')
            value = self._drivenCamera.driveBrightness(up)
        elif self._availableValues[self._valueSelected][1] == "SHUTTER":
            # TODO
            # print(('increasing' if up else 'decreasing') + ' shutter speed')
            value = self._drivenCamera.driveShutter(up)
        elif self._availableValues[self._valueSelected][1] == "APERTURE":
            # TODO
            # print(('increasing' if up else 'decreasing') + ' aperture')
            value = self._drivenCamera.driveAperture(up)
        self._availableValues[self._valueSelected][2] = value
        self._drawDriveButtons(0, 0)
    
    def _moveCameraAutofocusPressed_callback(self, pressed: bool, key: int, context: None):
        if pressed:
            self._drivenCamera.lockFocus(False)
            self._drivenCamera.refocus()
            self._renderIcon('icoAutofocus_b.png', None, "#4AA1FF", key)
        else:
            self._drivenCamera.lockFocus(True)
            self._renderIcon('icoAutofocus_b.png', None, None, key)

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
        self._renderIcon(f'icoSpeed{self._camDriveSpeed}.png', None, None, key)

    def _camSelectPressed_callback(self, pressed: bool, key: int, cam: ptz.Camera):
        if not pressed:
            return
        self._obs.setPreviewCamera(cam)
        self._selectedCam = cam
        if self._deckSize == 'REGULAR':
            self._drawDeck('CAMSELECT')
        elif self._deckSize == 'XL':
            self._obs.callPreset(None, cam)
            self._drawDeck('HOME')

    def _goToPagePressed_callback(self, pressed: bool, key: int, page: str):
        if not pressed:
            return
        self._drawDeck(page)
