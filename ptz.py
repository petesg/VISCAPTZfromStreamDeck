import socket
import time
import select
from urllib import response
from __time import curMillis

class Camera:

    def __init__(self, ip, port, channel) -> None:
        self._ip = ip
        self._port = port
        self._channel = channel
        self._pan = -1
        self._tilt = -1
        self._zoom = -1
        self._awaiting = [] # tuples of (awaited message, handler)

    def moveToPoint(self, p, t, z):
        moveMsg = f"8{self._channel:01X}01060218140{(p >> 12) & 0xF}0{(p >> 8) & 0xF}0{(p >> 4) & 0xF}0{p & 0xF}0{(t >> 12) & 0xF}0{(t >> 8) & 0xF}0{(t >> 4) & 0xF}0{t & 0xF}FF"
        zoomMsg = f"8{self._channel:01X}0104570{(z >> 12) & 0xF}0{(z >> 8) & 0xF}0{(z >> 4) & 0xF}0{z & 0xF}FF"
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind((self._ip, self._port))
        self._sendAndAck(sock, moveMsg, 3, 2000) # TODO do something if returns false
        self._sendAndAck(sock, zoomMsg, 3, 2000)
        response = self._waitForPacket(sock, 1000)
        if response != bytes.fromhex(f"905{self._channel}FF"): # completion message
            pass # TODO something...
        
    
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
        while not ack and retries:
            sock.send(msg)
            response = self._waitForPacket(sock, ts - int(time.time() * 1000)) # TODO reset timeout depending on type of NAK response
            # TODO account for replies to come in out of order (i.e. a reply to something else comes in before the ack for this one)
            # cache messages that aren't an ack away and remember to check them elsewhere?
            # OR make a list of awaited messages to check against
            if response == bytes.fromhex(f"904{self._channel}FF"): # ACK packet
                ack = True
            else:
                retries -= 1
        return ack
    
    def _clearAwaiting(self, sock, timeout):
        ts = curMillis() + timeout
        while curMillis() < ts and len(self._awaiting):
            ireceived = -1
            response = self._waitForPacket(sock, ts - curMillis())
            for i in range(len(self._awaiting)):
                if self._awaiting[i][0] == response:
                    if self._awaiting[i] is not None:
                        self._awaiting[i](response)
                    ireceived = i
                    break
            if ireceived != -1:
                del self._awaiting[ireceived]
        return not len(self._awaiting)
