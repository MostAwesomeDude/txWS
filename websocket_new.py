# Copyright (c) 2011 Oregon State University

"""
Blind reimplementation of WebSockets as a standalone wrapper for Twisted
protocols.
"""

from base64 import b64encode, b64decode
from hashlib import md5
from string import digits
from struct import pack

from twisted.internet import reactor
from twisted.protocols.policies import ProtocolWrapper, WrappingFactory
from twisted.python import log
from twisted.web.http import datetimeToString

REQUEST, NEGOTIATING, HYBI00_CHALLENGE, FRAMES = range(4)

encoders = {
    "base64": b64encode,
}

decoders = {
    "base64": b64decode,
}

def http_headers(s):
    """
    Create a dictionary of data from raw HTTP headers.
    """

    d = {}

    for line in s.split("\r\n"):
        try:
            key, value = [i.strip() for i in line.split(":", 1)]
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
    codec = None
    location = "/"
    origin = "http://example.com"
    state = REQUEST

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
            "Sec-WebSocket-Origin: %s\r\n" % self.origin,
            "Sec-WebSocket-Location: %s%s\r\n" % (self.origin, self.location),
            "WebSocket-Protocol: %s\r\n" % self.codec,
            "Sec-WebSocket-Protocol: %s\r\n" % self.codec,
            "\r\n",
        ])

    def parse_frames(self):
        """
        Find frames in incoming data and pass them to the underlying protocol.
        """

        start = self.buf.find("\x00")

        while start != -1:
            end = self.buf.find("\xff")
            if end == -1:
                # Incomplete frame, try again later.
                return
            else:
                frame, self.buf = self.buf[start + 1:end], self.buf[end + 1:]
                # Decode the frame, if we have a decoder.
                if self.codec:
                    frame = decoders[self.codec](frame)
                # Pass the frame to the underlying protocol.
                ProtocolWrapper.dataReceived(self, frame)
            start = self.buf.find("\x00")

    def send_frames(self):
        """
        Send all pending frames.
        """

        if self.state == FRAMES:
            for frame in self.pending_frames:
                # Encode the frame before sending it.
                if self.codec:
                    frame = encoders[self.codec](frame)
                self.transport.write("\x00%s\xff" % frame)
            self.pending_frames = []

    def validate_headers(self):
        """
        Check received headers for sanity and correctness, and stash any data
        from them which will be required later.
        """

        # Obvious but necessary.
        if not is_websocket(self.headers):
            log.msg("Not handling non-WS request")
            return False

        # Stash origin for those browsers that care about it.
        if "Origin" in self.headers:
            self.origin = self.headers["Origin"]

        # Check whether a codec is needed. WS calls this a "protocol" for
        # reasons I cannot fathom.
        protocol = None
        if "WebSocket-Protocol" in self.headers:
            protocol = self.headers["WebSocket-Protocol"]
        elif "Sec-WebSocket-Protocol" in self.headers:
            protocol = self.headers["Sec-WebSocket-Protocol"]

        if protocol:
            if protocol not in encoders or protocol not in decoders:
                log.msg("Couldn't handle WS protocol %s!" % protocol)
                return False
            self.codec = protocol

        # Start the next phase of the handshake for HyBi-00.
        if is_hybi00(self.headers):
            log.msg("Starting HyBi-00/Hixie-76 handshake")
            self.state = HYBI00_CHALLENGE

        return True

    def dataReceived(self, data):
        self.buf += data

        if self.state == REQUEST:
            if "\r\n" in self.buf:
                request, chaff, self.buf = self.buf.partition("\r\n")
                try:
                    verb, self.location, version = request.split(" ")
                except ValueError:
                    self.loseConnection()
                else:
                    self.state = NEGOTIATING
                    reactor.callLater(0, self.dataReceived, "")

        elif self.state == NEGOTIATING:
            # Check to see if we've got a complete set of headers yet.
            if "\r\n\r\n" in self.buf:
                head, chaff, self.buf = self.buf.partition("\r\n\r\n")
                self.headers = http_headers(head)
                # Validate headers. This will cause a state change.
                if self.validate_headers():
                    # Try to run the dataReceived() hook again; oftentimes
                    # there will be a handshake in the same packet as the
                    # headers!
                    reactor.callLater(0, self.dataReceived, "")
                else:
                    self.loseConnection()

        elif self.state == HYBI00_CHALLENGE:
            if len(self.buf) >= 8:
                challenge, self.buf = self.buf[:8], self.buf[8:]
                response = complete_hybi00(self.headers, challenge)
                self.send_websocket_preamble()
                self.transport.write(response)
                # Start sending frames, and kick any pending frames.
                self.state = FRAMES
                self.send_frames()

        elif self.state == FRAMES:
            self.parse_frames()

    def write(self, data):
        """
        Write to the transport.

        This method will only be called by the underlying protocol.
        """

        self.pending_frames.append(data)
        self.send_frames()

class WebSocketFactory(WrappingFactory):
    """
    Factory which wraps another factory to provide WebSockets transports for
    all of its protocols.
    """

    protocol = WebSocketProtocol
