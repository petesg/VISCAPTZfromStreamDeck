import os
import threading

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
    _callPreset: Callable[[str], None]
    _keyHandlers: list[tuple[Callable[[bool, int, Any], None], Any]]
    _selectedCams: list[str]
    
    def __init__(self, loadedConfig: SimpleNamespace, presetCallback: Callable[[str], None]):
        self._config = loadedConfig
        self._callPreset = presetCallback

        self._connectSurface()

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

        # Set initial key images.
        self._drawDeck()
        # for key in range(self._deck.key_count()):
        #     # TODO set key icons for home page
        #     pass
    
    def _disconnectSurface(self):
        # TODO close some threads or something?
        self._deck.close()
        self._deck = None
    
    def _drawDeck(self, page):
        # clear keys
        for i in range(len(self._deck.key_count())):
            self._keyHandlers[i] = (None, None)
            self._renderIcon(None, None, None, i)
        if page == "HOME":
            # populate preset buttons
            i = 0
            for p in list(loadedConfig.Presets.__dict__):
                if (i + 1) % self._deck.KEY_COLS == 0:
                    i += 1
                self._renderIcon(p.icon, p.label, None, i)
                self._keyHandlers[i] = (self._presetKeyPressed_callback, p)
                i += 1
            # camera button
            i = self._deck.KEY_COLS - 1
            self._renderIcon("cameraIcon.png", ', '.join(self._selectedCams), None, i)
            self._keyHandlers[i] = (self._camsKeyPressed_callback, None)
            # edit button
            i = self._deck.KEY_COLS * 2 - 1
            self._renderIcon("editIcon.png", "", None, i)
            self._keyHandlers[i] = (self._editPresetsPressed_callback, None)
        else:
            # TODO error, bad page name
            pass

    def _renderIcon(self, iconFile: str, label: str, borderColor: str, key: int) -> None:
        # resize icon file
        icon = Image.open(os.path.join(self._loadedConfig.AssetsPath, iconFile))
        image = PILHelper.create_scaled_image(self._deck, icon)
        draw = ImageDraw.Draw(image)

        # add border
        if borderColor:
            draw.rounded_rectangle((2, 2, image.width - 2, image.height - 2), 5, '#00000000', borderColor, 5)

        # add label
        if label:
            # wrap text
            font = ImageFont.truetype(os.path.join(self._loadedConfig.AssetsPath, 'Roboto-Regular.ttf'), 14)
            lines = [label]
            temp = ''
            while draw.textlength(lines[-1], font) >= image.width:
                splindex = lines[-1].rfind(' ')
                if splindex < 0:
                    break
                temp = lines[-1][splindex:] + temp
                lines[-1] = lines[-1][:splindex]
                if draw.textlength(lines[-1], font) < image.width:
                    lines.append(temp[1:])
            # overlay text
            draw.multiline_text((image.width / 2, image.height - 3), '\n'.join(lines), 'white', font, "md")

        self._deck.set_key_image(key, PILHelper.to_native_format(self._deck, image))

    def _camsKeyPressed_callback(self, state: bool, key: int, context: Any) -> None:
        # TODO
        pass

    def _editPresetsPressed_callback(self, state: bool, key: int, context: Any) -> None:
        # TODO
        pass

    def _presetKeyPressed_callback(self, state: bool, key: int, preset: str) -> None:
        if not state:
            return
        # TODO don't do anything if a preset is already being called (does that already take care of itself bc we're not using asynch callback and this blocks?)
        p = getattr(loadedConfig.Presets, preset)
        self._renderIcon(p.icon, p.label, 'yellow', key)
        self._callPreset(preset)
        # TODO move delay here (wait, why again?)
        self._renderIcon(p.icon, p.label, 'red', key)
        # TODO save what preset is being viewed so it can be re-highlighted if the deck is redrawn

    def _globalKeyPressed_callback(self, deck, key, state):
        (handler, context) = self._keyHandlers[key]
        handler(state, key, context)
        pass

# EXAMPLE CODE
# ------------


# Folder location of image assets used by this example.
ASSETS_PATH = os.path.join(os.path.dirname(__file__), "examples\\Assets")

# Generates a custom tile with run-time generated text and custom image via the
# PIL module.
def render_key_image(deck, icon_filename, font_filename, label_text):
    # Resize the source image asset to best-fit the dimensions of a single key,
    # leaving a margin at the bottom so that we can draw the key title
    # afterwards.
    icon = Image.open(icon_filename)
    image = PILHelper.create_scaled_image(deck, icon, margins=[0, 0, 20, 0])

    # Load a custom TrueType font and use it to overlay the key index, draw key
    # label onto the image a few pixels from the bottom of the key.
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(font_filename, 14)
    draw.text((image.width / 2, image.height - 5), text=label_text, font=font, anchor="ms", fill="white")

    return PILHelper.to_native_format(deck, image)


# Returns styling information for a key based on its position and state.
def get_key_style(deck, key, state):
    # Last button in the example application is the exit button.
    exit_key_index = deck.key_count() - 1

    if key == exit_key_index:
        name = "exit"
        icon = "{}.png".format("Exit")
        font = "Roboto-Regular.ttf"
        label = "Bye" if state else "Exit"
    else:
        name = "emoji"
        icon = "{}.png".format("Pressed" if state else "Released")
        font = "Roboto-Regular.ttf"
        label = "Pressed!" if state else f"Key {key}"

    return {
        "name": name,
        "icon": os.path.join(ASSETS_PATH, icon),
        "font": os.path.join(ASSETS_PATH, font),
        "label": label
    }


# Creates a new key image based on the key index, style and current key state
# and updates the image on the StreamDeck.
def update_key_image(deck, key, state):
    # Determine what icon and label to use on the generated key.
    key_style = get_key_style(deck, key, state)

    # Generate the custom key with the requested image and label.
    image = render_key_image(deck, key_style["icon"], key_style["font"], key_style["label"])

    # Use a scoped-with on the deck to ensure we're the only thread using it
    # right now.
    with deck:
        # Update requested key with the generated image.
        deck.set_key_image(key, image)


# Prints key state change information, updates rhe key image and performs any
# associated actions when a key is pressed.
def key_change_callback(deck, key, state):
    # Print new key state
    # print("Deck {} Key {} = {}".format(deck.id(), key, state), flush=True)
    print(f"Key {key} = {state}", flush=True)

    # Update the key image based on the new key state.
    update_key_image(deck, key, state)

    # Check if the key is changing to the pressed state.
    if state:
        key_style = get_key_style(deck, key, state)

        # When an exit button is pressed, close the application.
        if key_style["name"] == "exit":
            # Use a scoped-with on the deck to ensure we're the only thread
            # using it right now.
            with deck:
                # Reset deck, clearing all button images.
                deck.reset()

                # Close deck handle, terminating internal worker threads.
                deck.close()

                print("EXIT")


if __name__ == "__main__":
    streamdecks = DeviceManager().enumerate()

    print("Found {} Stream Deck(s).\n".format(len(streamdecks)))

    for index, deck in enumerate(streamdecks):
        # This example only works with devices that have screens.
        if not deck.is_visual():
            continue

        deck.open()
        deck.reset()

        print("Opened '{}' device (serial number: '{}', fw: '{}')".format(
            deck.deck_type(), deck.get_serial_number(), deck.get_firmware_version()
        ))

        # Set initial screen brightness to 30%.
        deck.set_brightness(30)

        # Set initial key images.
        for key in range(deck.key_count()):
            update_key_image(deck, key, False)

        # Register callback function for when a key state changes.
        deck.set_key_callback(key_change_callback)

        with open('config.json') as configFile:
            jsonData = configFile.read()
        loadedConfig = json.loads(jsonData, object_hook=lambda d: SimpleNamespace(**d))

        # d = ViscaDeck(loadedConfig, None)
        # d.connectStreamDeck()

        # Wait until all application threads have terminated (for this example,
        # this is when all deck handles are closed).
        for t in threading.enumerate():
            try:
                t.join()
            except RuntimeError:
                pass

        deck.disconnectStreamDeck()
