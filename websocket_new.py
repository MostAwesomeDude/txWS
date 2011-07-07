# Copyright (c) 2011 Oregon State University

"""
Blind reimplementation of WebSockets as a standalone wrapper for Twisted
protocols.
"""

from hashlib import md5
from string import digits
from struct import pack

from twisted.protocols.policies import ProtocolWrapper, WrappingFactory
from twisted.web.http import datetimeToString
from twisted.python import log

NEGOTIATING, HYBI00_CHALLENGE, FRAMES = range(3)

def http_headers(s):
    """
    Create a dictionary of data from raw HTTP headers.
    """

    d = {}

    for line in s.split("\r\n"):
        try:
            key, value = [i.strip() for i in line.split(":")]
            d[key] = value
        except ValueError:
            pass

    return d

def is_websocket(headers):
    """
    Determine whether a given set of headers is asking for WebSockets.
    """

    return (headers.get("Connection") == "Upgrade"
            and headers.get("Upgrade") == "WebSocket")

def is_hybi00(headers):
    """
    Determine whether a given set of headers is HyBi-00-compliant.

    Hixie-76 and HyBi-00 use a pair of keys in the headers to handshake with
    servers.
    """

    return "Sec-WebSocket-Key1" in headers and "Sec-WebSocket-Key2" in headers

def complete_hybi00(headers, challenge):
    """
    Generate the response for a HyBi-00 challenge.
    """

    key1 = headers["Sec-WebSocket-Key1"]
    key2 = headers["Sec-WebSocket-Key2"]

    first = int("".join(i for i in key1 if i in digits)) / key1.count(" ")
    second = int("".join(i for i in key2 if i in digits)) / key2.count(" ")

    nonce = pack(">II8s", first, second, challenge)

    return md5(nonce).digest()

class WebSocketProtocol(ProtocolWrapper):
    """
    Protocol which wraps another protocol to provide a WebSockets transport
    layer.
    """

    buf = ""
    state = NEGOTIATING

    def __init__(self, *args, **kwargs):
        ProtocolWrapper.__init__(self, *args, **kwargs)
        self.pending_frames = []

    def send_websocket_preamble(self):
        self.transport.writeSequence([
            "HTTP/1.1 101 FYI I am not a webserver\r\n",
            "Server: TwistedWebSocketWrapper/1.0\r\n",
            "Date: %s\r\n" % datetimeToString(),
            "Upgrade: WebSocket\r\n",
            "Connection: Upgrade\r\n",
        ])

    def parse_frames(self):
        """
        Find frames in incoming data and pass them to the underlying protocol.
        """

        while self.buf.startswith("\x00"):
            end = self.buf.find("\xff")
            if end == -1:
                # Incomplete frame, try again later.
                return
            else:
                frame, self.buf = self.buf[1:end], self.buf[end + 1:]
                # Pass the frame to the underlying protocol.
                ProtocolWrapper.dataReceived(self, frame)

    def send_frames(self):
        """
        Send all pending frames.
        """

        if self.state == FRAMES:
            for frame in self.pending_frames:
                self.transport.write("\x00%s\xff" % frame)
            self.pending_frames = []

    def dataReceived(self, data):
        self.buf += data
        log.msg("buf %r" % self.buf)

        if self.state == NEGOTIATING:
            # Check to see if we've got a complete set of headers yet.
            if "\r\n\r\n" in self.buf:
                head, chaff, self.buf = self.buf.partition("\r\n\r\n")
                self.headers = http_headers(head)
                if not is_websocket(self.headers):
                    self.loseConnection()
                if is_hybi00(self.headers):
                    self.state = HYBI00_CHALLENGE

        elif self.state == HYBI00_CHALLENGE:
            if len(self.buf) >= 8:
                challenge, self.buf = self.buf[:8], self.buf[8:]
                response = complete_hybi00(self.headers, challenge)
                self.send_websocket_preamble()
                self.transport.write(response)
                self.state = FRAMES

        elif self.state == FRAMES:
            self.parse_frames()

    def write(self, data):
        """
        Write to the transport.

        This method will only be called by the underlying protocol.
        """

        log.msg("frame %r" % data)

        self.pending_frames.append(data)
        self.send_frames()

class WebSocketFactory(WrappingFactory):
    """
    Factory which wraps another factory to provide WebSockets transports for
    all of its protocols.
    """

    protocol = WebSocketProtocol
