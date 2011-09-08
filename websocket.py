# Copyright (c) 2011 Oregon State University

"""
Blind reimplementation of WebSockets as a standalone wrapper for Twisted
protocols.
"""

from base64 import b64encode, b64decode
from hashlib import md5, sha1
from string import digits
from struct import pack

from twisted.internet.interfaces import ISSLTransport
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

def is_hybi_07(headers):
    """
    Determine whether a given set of headers asks for HyBi-07.
    """

    return headers.get("Sec-WebSocket-Version") == 7

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

def make_accept(key):
    """
    Create an "accept" response for a given key.

    This dance is expected to somehow magically make WebSockets secure.
    """

    guid = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

    return sha1("%s%s" % (key, guid)).digest().encode("base64").strip()

class WebSocketProtocol(ProtocolWrapper):
    """
    Protocol which wraps another protocol to provide a WebSockets transport
    layer.
    """

    buf = ""
    codec = None
    location = "/"
    host = "example.com"
    origin = "http://example.com"
    state = REQUEST

    def __init__(self, *args, **kwargs):
        ProtocolWrapper.__init__(self, *args, **kwargs)
        self.pending_frames = []

    def isSecure(self):
        """
        Borrowed technique for determining whether this connection is over
        SSL/TLS.
        """

        return ISSLTransport(self.transport, None) is not None

    def sendCommonPreamble(self):
        """
        Send the preamble common to all WebSockets connections.

        This might go away in the future if WebSockets continue to diverge.
        """

        self.transport.writeSequence([
            "HTTP/1.1 101 FYI I am not a webserver\r\n",
            "Server: TwistedWebSocketWrapper/1.0\r\n",
            "Date: %s\r\n" % datetimeToString(),
            "Upgrade: WebSocket\r\n",
            "Connection: Upgrade\r\n",
        ])

    def sendHyBi00Preamble(self):
        """
        Send a HyBi-00 preamble.
        """

        protocol = "wss" if self.isSecure() else "ws"

        self.sendCommonPreamble()

        self.transport.writeSequence([
            "Sec-WebSocket-Origin: %s\r\n" % self.origin,
            "Sec-WebSocket-Location: %s://%s%s\r\n" % (protocol, self.host,
                                                       self.location),
            "WebSocket-Protocol: %s\r\n" % self.codec,
            "Sec-WebSocket-Protocol: %s\r\n" % self.codec,
            "\r\n",
        ])

    def parseFrames(self):
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

    def sendFrames(self):
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

    def validateHeaders(self):
        """
        Check received headers for sanity and correctness, and stash any data
        from them which will be required later.
        """

        # Obvious but necessary.
        if not is_websocket(self.headers):
            log.msg("Not handling non-WS request")
            return False

        # Stash host and origin for those browsers that care about it.
        if "Host" in self.headers:
            self.host = self.headers["Host"]
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

        oldstate = None

        while oldstate != self.state:
            oldstate = self.state

            # Handle initial requests. These look very much like HTTP
            # requests, but aren't. We need to capture the request path for
            # those browsers which want us to echo it back to them (Chrome,
            # mainly.)
            # These lines look like:
            # GET /some/path/to/a/websocket/resource HTTP/1.1
            if self.state == REQUEST:
                if "\r\n" in self.buf:
                    request, chaff, self.buf = self.buf.partition("\r\n")
                    try:
                        verb, self.location, version = request.split(" ")
                    except ValueError:
                        self.loseConnection()
                    else:
                        self.state = NEGOTIATING

            elif self.state == NEGOTIATING:
                # Check to see if we've got a complete set of headers yet.
                if "\r\n\r\n" in self.buf:
                    head, chaff, self.buf = self.buf.partition("\r\n\r\n")
                    self.headers = http_headers(head)
                    # Validate headers. This will cause a state change.
                    if not self.validateHeaders():
                        self.loseConnection()

            elif self.state == HYBI00_CHALLENGE:
                if len(self.buf) >= 8:
                    challenge, self.buf = self.buf[:8], self.buf[8:]
                    response = complete_hybi00(self.headers, challenge)
                    self.sendHyBi00Preamble()
                    self.transport.write(response)
                    log.msg("Completed HyBi-00/Hixie-76 handshake")
                    # Start sending frames, and kick any pending frames.
                    self.state = FRAMES
                    self.sendFrames()

            elif self.state == FRAMES:
                self.parseFrames()

    def write(self, data):
        """
        Write to the transport.

        This method will only be called by the underlying protocol.
        """

        self.pending_frames.append(data)
        self.sendFrames()

class WebSocketFactory(WrappingFactory):
    """
    Factory which wraps another factory to provide WebSockets transports for
    all of its protocols.
    """

    protocol = WebSocketProtocol
