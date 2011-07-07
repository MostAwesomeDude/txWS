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

NEGOTIATING, HYBI00_CHALLENGE, FRAMES = range(3)

def http_headers(s):
    """
    Create a dictionary of data from raw HTTP headers.
    """

    d = {}

    for line in s.split("\n"):
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

    def send_websocket_preamble(self):
        self.transport.writeSequence([
            "HTTP/1.1 101 FYI I am not a webserver\n",
            "Server: TwistedWebSocketWrapper/1.0\n",
            "Date: %s\n" % datetimeToString(),
            "Upgrade: WebSocket\n",
            "Connection: Upgrade\n",
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

    def connectionMade(self):
        # Overriden to prevent the underlying protocol from getting started.
        # We'll explicitly call connectionMade() later.
        pass

    def dataReceived(self, data):
        self.buf += data

        if self.state == NEGOTIATING:
            # Check to see if we've got a complete set of headers yet.
            if "\n\n" in self.buf:
                head, chaff, self.buf = self.buf.partition("\n\n")
                headers = http_headers(head)
                if not is_websocket(headers):
                    self.loseConnection()
                if is_hybi00(headers):
                    state = HYBI00_CHALLENGE

        elif self.state == HYBI00_CHALLENGE:
            if len(self.buf) >= 8:
                challenge, self.buf = self.buf[:8], self.buf[8:]
                response = complete_hybi00(challenge)
                self.send_websocket_preamble()
                self.transport.write(response)
                # Start the underlying protocol.
                ProtocolWrapper.connectionMade(self)
                self.state = FRAMES

        elif self.state == FRAMES:
            self.parse_frames()

class WebSocketFactory(WrappingFactory):
    """
    Factory which wraps another factory to provide WebSockets transports for
    all of its protocols.
    """

    protocol = WebSocketProtocol
