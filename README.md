# VISCAPTZfromStreamDeck

OBS plugin script to control VISCA-protocol PTZ cameras via a Elgato Stream Deck.

## Installation

1. Install [HID API backend](https://python-elgato-streamdeck.readthedocs.io/en/stable/pages/backend_libusb_hidapi.html) required for Stream Deck control.
2. Add `obs-viscadeck-main.py` to scripts in OBS.
3. Set up config file and select from script setup in OBS.  (See example config.json file.)

# Code Overview

This project has three modules:

* `obs.py` defines the script setup UI and controls OBS functions (transitioning scenes and starting/stopping stream).
* `ptz.py` handles the interface for controlling the PTZ cameras over UDP with VISCA commands.
* `buttons.py` sets up the stream deck interface.

The `obs.py` module serves as an entry point for the plugin.  However, all post-setup duties performed by the plugin are driven by event handlers triggered in `buttons.py` by the stream deck.

## obs.py

As mentioned, this module serves as the entry point for the plugin.  The first section is labeled `# intrinsics` and defines a number of functions used by OBS to configure the script's setup interface and some actions that are triggered by OBS.  This is mostly setting up the config UI as we don't use any OBS-triggered events after loading (all our actions will be triggered by button presses on the Stream Deck).  See [obspython reference](https://github.com/upgradeQ/Streaming-Software-Scripting-Reference) for details on the OBS scripting api.

The `configureMain()` function covers all primary setup for the plugin:
* Loads the json config file.
* Instantiates a camera object (see [ptz module](#ptz)) for each of the cameras in the loaded config.
* Kicks off the [Stream Deck module](#buttons.py) which will serve as the source for all actions performed by the plugin.

The rest of this module defines a number of callbacks used by the other modules to execute actions in OBS such as switching preview/live scenes and starting/stopping the stream.

## ptz.py

This module defines the `Camera` class which handles communication with a given camera.  Camera control is done over UDP via [VISCA protocol](https://en.wikipedia.org/wiki/VISCA_Protocol) commands.

### Communication Scheme

Most commands sent to the camera should trigger an immediate ACK or NAK response from the camera, followed by the camera's reply to the specific command sent.  The exception to this rule is that inquiry type commands return only the response with no ACK/NAK.

With this in mind, two methods are implemented to handle traffic with the cameras:
* `_sendAndAck()` is used to send commands which expect an ACK/NAK response and will block until either the response is received or a timeout is reached, returning whether the command was ACKed.
  - Inquiry commands which don't expect an ACK can be sent with the socket's `.send()` method directly instead of using this method.
  - Any non ACK/NAK responses received while waiting for the ACK/NAK will be saved to the `_sparePackets` list for later reference by `_clearAwaiting()`.
* `_clearAwaiting()` will block until all messages in the `_awaiting` list have been received.
  - `_awaiting` is a list of tuples containing regex patterns to identify expected responses, paired with handler functions to process the identified response packets.

A typical exchange with the camera will look like this:
1. Send one or more command packets with `_sendAndAck()` or inquiry packets with `Socket.send()`.
2. Append expected response patterns to `_awaiting` with corresponding response handlers.
  - Response handlers are typically implemented to save information contained in response to some property variable.\
3. Call `_clearAwaiting()` to block until all responses are received.

### Camera Controls

Most camera functions use a trivial application of the above scheme.  See included [VISCA command list](PTZOptics-VISCA-over-IP-Rev-1_2-8-20.pdf) for reference.

#### Brightness Controls Hack for PTZ Optics Brand Cameras

My experience with the particular "PTZ Optics" brand of cameras I use has been that they struggle mightily with the basic brightness controls.  Using the (`81 01 04 0D ...`) commands under the `CAM_Bright` section of the command list document results in inconsistent behavior from the cameras - sometimes the up/down commands seem to do nothing at all and sometimes the camera seems to fight the commands being sent by immediately readjusting the brightness itself.

Furthermore, my cameras even seem to sometimes fight the shutter speed and aperture up/down commands (`81 01 04 0A/0B 02/03 FF`).  Despite being in manual exposure mode (with `81 01 04 39 03 FF`), my cameras frequently either ignore these commands or immediately readjust the brightness after making the requested change for only a fraction of a second.

To get around this, the `driveShutter()` and `driveAperture()` do not use the relevant up/down commands, but instead first query the camera's current shutter/aperture setting and then use the absolute set command to set the incremented value directly.
