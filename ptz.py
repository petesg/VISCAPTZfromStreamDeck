import socket
import time
import select
# from urllib import response # TODO is this supposed to be here or did it get auto added inadvertently???
from __time import curMillis

class Camera:

    def __init__(self, ip, port, channel) -> None:
        self._ip = ip
        self._port = port
        self._channel = channel
        self._pan = -1
        self._tilt = -1
        self._zoom = -1
        self._awaiting = [] # tuples of (awaited message, handler) [can't be a dict since duplicates are allowed]
        self._sparePackets = [] # received packets that weren't being awaited at the time

    def moveToPoint(self, p, t, z):
        moveMsg = f"8{self._channel:01X}01060218140{(p >> 12) & 0xF}0{(p >> 8) & 0xF}0{(p >> 4) & 0xF}0{p & 0xF}0{(t >> 12) & 0xF}0{(t >> 8) & 0xF}0{(t >> 4) & 0xF}0{t & 0xF}FF"
        zoomMsg = f"8{self._channel:01X}0104570{(z >> 12) & 0xF}0{(z >> 8) & 0xF}0{(z >> 4) & 0xF}0{z & 0xF}FF"
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind((self._ip, self._port))
        self._sendAndAck(sock, bytes.fromhex(moveMsg), 3, 2000) # TODO do something if returns false
        self._sendAndAck(sock, bytes.fromhex(zoomMsg), 3, 2000)
        self._awaiting += 2 * [(bytes.fromhex(f"905{self._channel}FF"), None)] # completion message
        self._clearAwaiting(sock, 3000)
        sock.close()
    
    def _updatePosition(self):
        zoomInqMsg = f"" # TODO
        posInqMsg = f"" # TODO
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind((self._ip, self._port))
        self._sendAndAck(sock, bytes.fromhex(zoomInqMsg), 3, 2000)
        self._sendAndAck(sock, bytes.fromhex(posInqMsg), 3, 2000)
        self._awaiting.append((bytes.fromhex(f"XXXzoomRegexXXX"), self._unstuffZoom))
        self._awaiting.append((bytes.fromhex(f"XXXpanTiltRegexXXX"), self._unstuffTilt))
        self._clearAwaiting(sock, 3000)
        sock.close()

    def _unstuffZoom(self, packet):
        # TODO
        pass

    def _unstuffTilt(self, packet):
        # TODO
        pass
    
    def _waitForPacket(self, sock, timeout):
        ts = curMillis() + timeout
        buf = b"\x00"
        while buf[-1] != 0xFF:
            dataReady = select.select([sock], [], [], ts - curMillis())
            if dataReady[0]:
                data, addr = sock.recvfrom(4096)
                # TODO validate addr
                buf += data # TODO account for multiple messages strung together (so 0xFF is in the middle)
            if int(time.time() * 1000) > ts:
                return None
        return buf[1:]
    
    def _sendAndAck(self, sock, msg, retries, timeout):
        ts = curMillis() + timeout
        ack = False
        nak = False
        while not ack and retries:
            if nak:
                sock.send(msg)
            response = self._waitForPacket(sock, ts - int(time.time() * 1000)) # TODO reset timeout depending on type of NAK response
            # TODO account for replies to come in out of order (i.e. a reply to something else comes in before the ack for this one)
            # cache messages that aren't an ack away and remember to check them elsewhere? <- [doing this, mostly implemented now?]
            # OR make a list of awaited messages to check against
            if response == bytes.fromhex(f"904{self._channel}FF"): # ACK packet
                ack = True
            # elif response == bytes.fromhex(f"904{self._channel}FF"): # TODO check for NAK packets (there are several types)
            #     retries -= 1
            #     nak = True
            else:
                self._sparePackets += [response]
        return ack

    def _checkIfAwaited(self, packet):
        for i in range(len(self._awaiting)):
            if self._awaiting[i][0] == packet: # TODO need to use regex here instead of == (to allow for inquiry answers which pass unknowns)
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
