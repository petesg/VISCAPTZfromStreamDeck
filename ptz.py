import socket
import select
import re
# from urllib import response # TODO is this supposed to be here or did it get auto added inadvertently???
from __time import curMillis

class Camera:

    def __init__(self, ip, port, channel, name) -> None:
        self.name = name
        self._ip = ip
        self._port = port
        self._channel = channel
        self._pan = -1
        self._tilt = -1
        self._zoom = -1
        self._awaiting = [] # tuples of (awaited message, handler) [can't be a dict since duplicates are allowed]
        self._sparePackets = [] # received packets that weren't being awaited at the time

    def moveToPoint(self, p, t, z):
        # TODO TEMP test code without cameras attached:
        print(f"moving to (0x{p:X}, 0x{t:X}, 0x{z:X})")
        # return False
        moveMsg = f"8{self._channel:01X}01060218140{(p >> 12) & 0xF:01X}0{(p >> 8) & 0xF:01X}0{(p >> 4) & 0xF:01X}0{p & 0xF:01X}0{(t >> 12) & 0xF:01X}0{(t >> 8) & 0xF:01X}0{(t >> 4) & 0xF:01X}0{t & 0xF:01X}FF"
        zoomMsg = f"8{self._channel:01X}0104470{(z >> 12) & 0xF:01X}0{(z >> 8) & 0xF:01X}0{(z >> 4) & 0xF:01X}0{z & 0xF:01X}FF"
        print(f'move packet: "{moveMsg}"')
        print(f'zoom packet: "{zoomMsg}"')
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect((self._ip, self._port))
        if not self._sendAndAck(sock, bytes.fromhex(moveMsg), 3, 2000):
            return False # TODO do I need to do something else if returns false?
        if not self._sendAndAck(sock, bytes.fromhex(zoomMsg), 3, 2000):
            return False
        self._awaiting += 2 * [(re.compile(r"905[\da-f]ff$"), None)] # completion message
        print(f'awaiting {len(self._awaiting)} packets...')
        if not self._clearAwaiting(sock, 10000):
            return False
        sock.close()
        print(f'finishing with {len(self._awaiting)} awaited packets remaining')
        return True

    def getPosition(self):
        self._updatePosition()
        return (self._pan, self._tilt, self._zoom)
    
    def autofocus(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect((self._ip, self._port))
        if not self._sendAndAck(sock, bytes.fromhex(f"8{self._channel:01X}01043802FF"), 3, 2000):
            return False
        return True
    
    def drivePanTilt(self, pan: int, tilt: int) -> bool:
        """Drives camera at set velocity in P/T plane.

        ### Parameters
        `pan`: `int` - Pan speed, between -0x18 and 0x18

        `tilt`: `int` - Tilt speed, between -0x14 and 0x14

        ### Returns
        `bool` - Whether command was ACK'ed by camera.
        """
        pDir = 3 if pan == 0 else 2 if pan > 0 else 1
        tDir = 3 if tilt == 0 else 1 if tilt > 0 else 2
        pan = min(abs(int(pan)), 0x18)
        tilt = min(abs(int(tilt)), 0x14)
        
        driveStr = f'8{self._channel:01X}010601{pan:02X}{tilt:02X}0{pDir}0{tDir}FF'
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect((self._ip, self._port))
        if not self._sendAndAck(sock, bytes.fromhex(driveStr), 3, 2000):
            return False
        return True

    def driveZoom(self, speed: int):
        """Drives camera zoom at set velocity.

        ### Parameters
        `speed`: `int` - Zoom speed, between -0x7 and 0x7

        ### Returns
        `bool` - Whether command was ACK'ed by camera.
        """
        dir = 0 if speed == 0 else 2 if speed > 0 else 3
        speed = min(abs(int(speed)), 7)
        
        driveStr = f'8{self._channel:01X}010407{dir}{speed}FF'
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect((self._ip, self._port))
        if not self._sendAndAck(sock, bytes.fromhex(driveStr), 3, 2000):
            return False
        return True

    def driveShutter(self, up: bool):
        modeStr = f'8{self._channel:01X}01043903FF'
        driveStr = f'8{self._channel:01X}01040A0{"2" if up else "3"}FF'
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect((self._ip, self._port))
        # have to first make sure exposure mode is set to manual
        if not self._sendAndAck(sock, bytes.fromhex(modeStr), 3, 2000):
            return False
        if not self._sendAndAck(sock, bytes.fromhex(driveStr), 3, 2000):
            return False
        self._awaiting += [(re.compile(r"905[\da-f]ff$"), None)] # completion message
        print(f'awaiting {len(self._awaiting)} packets...')
        if not self._clearAwaiting(sock, 2000):
            return False
        return True
    
    def driveAperture(self, up: bool):
        modeStr = f'8{self._channel:01X}01043903FF'
        driveStr = f'8{self._channel:01X}01040B0{"2" if up else "3"}FF'
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect((self._ip, self._port))
        # have to first make sure exposure mode is set to manual
        if not self._sendAndAck(sock, bytes.fromhex(modeStr), 3, 2000):
            return False
        if not self._sendAndAck(sock, bytes.fromhex(driveStr), 3, 2000):
            return False
        self._awaiting += [(re.compile(r"905[\da-f]ff$"), None)] # completion message
        print(f'awaiting {len(self._awaiting)} packets...')
        if not self._clearAwaiting(sock, 2000):
            return False
        return True

    def _updatePosition(self):
        print('inquiring pos')
        zoomInqMsg = f"8{self._channel}090447FF" # TODO
        posInqMsg = f"8{self._channel}090612FF" # TODO
        print('setting up socket')
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect((self._ip, self._port))
        print('sending zomm inq.')
        # (apparently inquiry messages aren't ACK'ed)
        # TODO change sendAndAck to optionally not require ACK but still make sure no NAK is received
        # self._sendAndAck(sock, bytes.fromhex(zoomInqMsg), 3, 2000)
        sock.send(bytes.fromhex(zoomInqMsg)) # TODO temp, see above
        print('sending pan/tilt inq')
        # self._sendAndAck(sock, bytes.fromhex(posInqMsg), 3, 2000)
        sock.send(bytes.fromhex(posInqMsg)) # TODO temp, see above
        print('awaiting responses...')
        self._awaiting.append((re.compile(r"9050(0[\da-f]){4}ff$"), self._unstuffZoom))
        self._awaiting.append((re.compile(r"9050(0[\da-f]){8}ff$"), self._unstuffPanTilt))
        self._clearAwaiting(sock, 5000)
        print('responses received')
        sock.close()

    def _unstuffZoom(self, packet):
        self._zoom = (0x0F & packet[2]) << 12 | (0x0F & packet[3]) << 8 | (0x0F & packet[4]) << 4 | (0xF & packet[5])

    def _unstuffPanTilt(self, packet):
        self._pan = (0x0F & packet[2]) << 12 | (0x0F & packet[3]) << 8 | (0x0F & packet[4]) << 4 | (0x0F & packet[5])
        self._tilt = (0x0F & packet[6]) << 12 | (0x0F & packet[7]) << 8 | (0x0F & packet[8]) << 4 | (0x0F & packet[9])
    
    def _waitForPacket(self, sock, timeout):
        ts = curMillis() + timeout
        buf = b"\x00"
        while buf[-1] != 0xFF:
            dataReady = select.select([sock], [], [], (ts - curMillis()) / 1000)
            if dataReady[0]:
                data, addr = sock.recvfrom(4096)
                # TODO validate addr
                buf += data # TODO account for multiple messages strung together (so 0xFF is in the middle)
            if curMillis() > ts:
                return None
        return buf[1:]
    
    def _sendAndAck(self, sock, msg, retries, timeout):
        ts = curMillis() + timeout
        ack = False
        nak = True
        print(f'sending "{msg.hex()}"...')
        i = 0
        while not ack and retries and ts > curMillis():
            i += 1
            print(f'attempt {i}, awaiting response...')
            if nak:
                sock.send(msg)
                nak = False
            response = self._waitForPacket(sock, max(0, ts - curMillis())) # TODO reset timeout depending on type of NAK response
            # TODO account for replies to come in out of order (i.e. a reply to something else comes in before the ack for this one)
            # cache messages that aren't an ack away and remember to check them elsewhere? <- [doing this, mostly implemented now?]
            # OR make a list of awaited messages to check against
            # TODO the following code crashes if timeout is reached with no message received (because `response` is `None`)
            try:
                print(f'received "{response.hex()}" ({len(response)} bytes, raw: {response}) ')
                # TODO should I use a regex here instead of equality?
                # if response == bytes.fromhex(f"904{self._channel + 1}FF"): # ACK packet (channel gets +1 for some reason ?!??!?!)
                if re.compile(r"904[\da-f]ff$").match(response.hex()):
                    ack = True
                    print('response is ack')
                # elif response == bytes.fromhex(f"904{self._channel}FF"): # TODO check for NAK packets (there are several types)
                #     retries -= 1
                #     nak = True
                else:
                    self._sparePackets += [response]
                    print(f"response isn't ack (there are now {len(self._sparePackets)} spares stored)")
            except AttributeError:
                ack = False
                # there was no response
        return ack

    def _checkIfAwaited(self, packet):
        for i in range(len(self._awaiting)):
            if self._awaiting[i][0].match(packet.hex()):
                if self._awaiting[i][1] is not None:
                    self._awaiting[i][1](packet)
                del self._awaiting[i]
                return True
        return False
    
    def _clearAwaiting(self, sock, timeout):
        # first check _sparePackets to see if an awaited packet was received already while ack waiting
        for packet in self._sparePackets:
            self._checkIfAwaited(packet)
        ts = curMillis() + timeout
        while curMillis() < ts and len(self._awaiting):
            response = self._waitForPacket(sock, ts - curMillis())
            self._checkIfAwaited(response)
        return not len(self._awaiting)

if __name__ == "__main__":
    cam1 = Camera('192.168.10.11', 1259, 1, "CAMERA 1")
    cam2 = Camera('192.168.10.12', 1259, 1, "CAMERA 2")
