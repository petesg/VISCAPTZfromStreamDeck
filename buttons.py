import os
import threading

from PIL import Image, ImageDraw, ImageFont
from StreamDeck.DeviceManager import DeviceManager
from StreamDeck.ImageHelpers import PILHelper

class SDeck:
    
    def __init__(self, loadedConfig, presetCallback):
        global config
        config = loadedConfig
        self._callPreset = presetCallback

    
    # Generates a custom tile with run-time generated text and custom image via the
    # PIL module.
    def _renderKeyImage(deck, icon_filename, label_text):
        # Resize the source image asset to best-fit the dimensions of a single key,
        # leaving a margin at the bottom so that we can draw the key title
        # afterwards.
        icon = Image.open(icon_filename)
        image = PILHelper.create_scaled_image(deck, icon, margins=[0, 0, 20, 0])

        # Load a custom TrueType font and use it to overlay the key index, draw key
        # label onto the image a few pixels from the bottom of the key.
        # font_filename = ""
        draw = ImageDraw.Draw(image)
        # font = ImageFont.truetype(font_filename, 14)
        draw.text((image.width / 2, image.height - 5), text=label_text, anchor="ms", fill="white") # , font=font
        draw.text()

        return PILHelper.to_native_format(deck, image)
        
