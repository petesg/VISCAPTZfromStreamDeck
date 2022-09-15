import socket

class Camera:

    def __init__(self, ip, port, channel) -> None:
        self.ip = ip
        self.port = port
        self.channel = channel
        self.pan = -1
        self.tilt = -1
        self.zoom = -1

    def moveToPoint(self, p, t, z):
        moveMsg = f"8{self.channel:01X}01060218140{(p >> 12) & 0xF}0{(p >> 8) & 0xF}0{(p >> 4) & 0xF}0{p & 0xF}0{(t >> 12) & 0xF}0{(t >> 8) & 0xF}0{(t >> 4) & 0xF}0{t & 0xF}FF"
        zoomMsg = f"8{self.channel:01X}0104570{(z >> 12) & 0xF}0{(z >> 8) & 0xF}0{(z >> 4) & 0xF}0{z & 0xF}FF"
        
