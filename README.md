# VISCAPTZfromStreamDeck

Project to control VISCA-protocol PTZ cameras through OBS via a Elgato Stream Deck

Goal is to have Stream Deck buttons correspond to camera view presets.  Pressing a button moves whichever camera isn't live in OBS to that preset location then switches to it in OBS.  Option planned to force a selected camera to be used - if that camera is live it will move other camera to wide view and transition to it before moving requested camera.

## Installation

Install [HID API backend](https://python-elgato-streamdeck.readthedocs.io/en/stable/pages/backend_libusb_hidapi.html).

Setup cameras in config.json file.

Add `obs-viscadeck-main.py` to scripts in OBS.
