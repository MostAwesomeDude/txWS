# Copyright (c) 2011 Oregon State University Open Source Lab
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to
# deal in the Software without restriction, including without limitation the
# rights to use, copy, modify, merge, publish, distribute, sublicense, and/or
# sell copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
#    The above copyright notice and this permission notice shall be included
#    in all copies or substantial portions of the Software.
#
#    THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS
#    OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
#    MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN
#    NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM,
#    DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR
#    OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE
#    USE OR OTHER DEALINGS IN THE SOFTWARE.
#
# Copyright 2014 Google Inc. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License.  You may obtain a copy
# of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.  See the
# License for the specific language governing permissions and limitations under
# the License.

"""
Blind reimplementation of WebSockets as a standalone wrapper for Twisted
protocols.
"""

from __future__ import division

from twisted.web import resource, http
from twisted.web.server import NOT_DONE_YET

import six

import array

from base64 import b64encode, b64decode
from hashlib import md5, sha1
from string import digits
from struct import pack, unpack

from twisted.internet.interfaces import ISSLTransport
from twisted.protocols.policies import ProtocolWrapper, WrappingFactory
from twisted.python import log
from twisted.web.http import datetimeToString


class WSException(Exception):
    """
    Something stupid happened here.

    If this class escapes txWS, then something stupid happened in multiple
    places.
    """


# Flavors of WS supported here.
# HYBI00  - Hixie-76, HyBi-00. Challenge/response after headers, very minimal
#           framing. Tricky to start up, but very smooth sailing afterwards.
# HYBI07  - HyBi-07. Modern "standard" handshake. Bizarre masked frames, lots
#           of binary data packing.
# HYBI10  - HyBi-10. Just like HyBi-07. No, seriously. *Exactly* the same,
#           except for the protocol number.
# RFC6455 - RFC 6455. The official WebSocket protocol standard. The protocol
#           number is 13, but otherwise it is identical to HyBi-07.

HYBI00, HYBI07, HYBI10, RFC6455 = range(4)

# States of the state machine. Because there are no reliable byte counts for
# any of this, we don't use StatefulProtocol; instead, we use custom state
# enumerations. Yay!

REQUEST, NEGOTIATING, CHALLENGE, FRAMES = range(4)

# Control frame specifiers. Some versions of WS have control signals sent
# in-band. Adorable, right?

NORMAL, CLOSE, PING, PONG = range(4)

opcode_types = {
    0x0: NORMAL,
    0x1: NORMAL,
    0x2: NORMAL,
    0x8: CLOSE,
    0x9: PING,
    0xA: PONG,
}

encoders = {
    "base64": b64encode,
}

decoders = {
    "base64": b64decode,
}


# Fake HTTP stuff, and a couple convenience methods for examining fake HTTP
# headers.


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

    return (
        "upgrade" in headers.get("Connection", "").lower()
        and headers.get("Upgrade").lower() == "websocket"
    )


def is_hybi00(headers):
    """
    Determine whether a given set of headers is HyBi-00-compliant.

    Hixie-76 and HyBi-00 use a pair of keys in the headers to handshake with
    servers.
    """

    return "Sec-WebSocket-Key1" in headers and "Sec-WebSocket-Key2" in headers


# Authentication for WS.


def complete_hybi00(headers, challenge):
    """
    Generate the response for a HyBi-00 challenge.
    """

    key1 = headers["Sec-WebSocket-Key1"]
    key2 = headers["Sec-WebSocket-Key2"]

    first = int("".join(i for i in key1 if i in digits)) // key1.count(" ")
    second = int("".join(i for i in key2 if i in digits)) // key2.count(" ")

    nonce = pack(">II8s", first, second, six.b(challenge))

    return md5(nonce).digest()


def make_accept(key):
    """
    Create an "accept" response for a given key.

    This dance is expected to somehow magically make WebSockets secure.
    """

    guid = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

    accept = "%s%s" % (key, guid)
    hashed_bytes = sha1(accept.encode("utf-8")).digest()

    return b64encode(hashed_bytes).strip().decode("utf-8")


# Frame helpers.
# Separated out to make unit testing a lot easier.
# Frames are bonghits in newer WS versions, so helpers are appreciated.


def make_hybi00_frame(buf) -> list[bytes]:
    """
    Make a HyBi-00 frame from some data.

    This function does exactly zero checks to make sure that the data is safe
    and valid text without any 0xff bytes.
    """

    if isinstance(buf, six.text_type):
        buf = buf.encode("utf-8")

    return [six.b("\x00"), buf, six.b("\xff")]


def parse_hybi00_frames(buf):
    """
    Parse HyBi-00 frames, returning unwrapped frames and any unmatched data.

    This function does not care about garbage data on the wire between frames,
    and will actively ignore it.
    """

    start = buf.find(six.b("\x00"))
    tail = 0
    frames = []

    while start != -1:
        end = buf.find(six.b("\xff"), start + 1)
        if end == -1:
            # Incomplete frame, try again later.
            break
        else:
            # Found a frame, put it in the list.
            frame = buf[start + 1 : end]
            frames.append((NORMAL, frame))
            tail = end + 1
        start = buf.find(six.b("\x00"), end + 1)

    # Adjust the buffer and return.
    buf = buf[tail:]
    return frames, buf


def mask(buf, key):
    """
    Mask or unmask a buffer of bytes with a masking key.

    The key must be exactly four bytes long.
    """

    # This is super-duper-secure, I promise~
    key = array.array("B", key)
    buf = array.array("B", buf)
    for i in range(len(buf)):
        buf[i] ^= key[i % 4]
    return buf.tobytes()


def make_hybi07_frame(buf, opcode=0x1) -> list[bytes]:
    """
    Make a HyBi-07 frame.

    This function always creates unmasked frames, and attempts to use the
    smallest possible lengths.
    """

    if len(buf) > 0xFFFF:
        length = six.b("\x7f%s") % pack(">Q", len(buf))
    elif len(buf) > 0x7D:
        length = six.b("\x7e%s") % pack(">H", len(buf))
    else:
        length = six.b(chr(len(buf)))

    if isinstance(buf, six.text_type):
        buf = buf.encode("utf-8")

    # Always make a normal packet.
    header = chr(0x80 | opcode)
    return [six.b(header) + length, buf]


def make_hybi07_frame_dwim(buf) -> list[bytes]:
    """
    Make a HyBi-07 frame with binary or text data according to the type of buf.
    """

    # TODO: eliminate magic numbers.
    if isinstance(buf, six.binary_type):
        return make_hybi07_frame(buf, opcode=0x2)
    elif isinstance(buf, six.text_type):
        return make_hybi07_frame(buf.encode("utf-8"), opcode=0x1)
    else:
        raise TypeError(
            "In binary support mode, frame data must be either str or unicode"
        )


def parse_hybi07_frames(buf):
    """
    Parse HyBi-07 frames in a highly compliant manner.
    """

    start = 0
    frames = []

    while True:
        # If there's not at least two bytes in the buffer, bail.
        if len(buf) - start < 2:
            break

        # Grab the header. This single byte holds some flags nobody cares
        # about, and an opcode which nobody cares about.
        header = buf[start]

        if six.PY2:
            header = ord(header)

        if header & 0x70:
            # At least one of the reserved flags is set. Pork chop sandwiches!
            raise WSException("Reserved flag in HyBi-07 frame (%d)" % header)
            frames.append(("", CLOSE))
            return frames, buf

        # Get the opcode, and translate it to a local enum which we actually
        # care about.
        opcode = header & 0xF
        try:
            opcode = opcode_types[opcode]
        except KeyError:
            raise WSException("Unknown opcode %d in HyBi-07 frame" % opcode)

        # Get the payload length and determine whether we need to look for an
        # extra length.
        length = buf[start + 1]

        if six.PY2:
            length = ord(length)

        masked = length & 0x80
        length &= 0x7F

        # The offset we're gonna be using to walk through the frame. We use
        # this because the offset is variable depending on the length and
        # mask.
        offset = 2

        # Extra length fields.
        if length == 0x7E:
            if len(buf) - start < 4:
                break

            length = buf[start + 2 : start + 4]
            length = unpack(">H", length)[0]
            offset += 2
        elif length == 0x7F:
            if len(buf) - start < 10:
                break

            # Protocol bug: The top bit of this long long *must* be cleared;
            # that is, it is expected to be interpreted as signed. That's
            # fucking stupid, if you don't mind me saying so, and so we're
            # interpreting it as unsigned anyway. If you wanna send exabytes
            # of data down the wire, then go ahead!
            length = buf[start + 2 : start + 10]
            length = unpack(">Q", length)[0]
            offset += 8

        if masked:
            if len(buf) - (start + offset) < 4:
                break

            key = buf[start + offset : start + offset + 4]
            offset += 4

        if len(buf) - (start + offset) < length:
            break

        data = buf[start + offset : start + offset + length]

        if masked:
            data = mask(data, key)

        if opcode == CLOSE:
            if len(data) >= 2:
                # We have to unpack the opcode and return usable data here.
                data = unpack(">H", data[:2])[0], data[2:]
            else:
                # No reason given; use generic data.
                data = 1000, six.b("No reason given")

        frames.append((opcode, data))
        start += offset + length

    return frames, buf[start:]


class WebSocketProtocol(ProtocolWrapper):
    """
    Protocol which wraps another protocol to provide a WebSockets transport
    layer.
    """

    buf = six.b("")
    codec = None
    location = "/"
    host = "example.com"
    origin = "http://example.com"
    state = REQUEST
    flavor = None
    do_binary_frames = False

    def __init__(self, *args, **kwargs):
        ProtocolWrapper.__init__(self, *args, **kwargs)
        self.pending_frames = []
        self.headers = {}
        self._producerForWrite = None

    def setBinaryMode(self, mode):
        """
        If True, send str as binary and unicode as text.

        Defaults to false for backwards compatibility.
        """
        self.do_binary_frames = bool(mode)

    def registerProducer(self, producer, streaming):
        if hasattr(producer, "write") and hasattr(producer, "writeSequence"):
            self._producerForWrite = producer
        ProtocolWrapper.registerProducer(self, producer, streaming)

    def unregisterProducer(self):
        self._producerForWrite = None
        ProtocolWrapper.unregisterProducer(self)

    def isSecure(self):
        """
        Borrowed technique for determining whether this connection is over
        SSL/TLS.
        """

        return ISSLTransport(self.transport, None) is not None

    def writeEncoded(self, data):
        if isinstance(data, six.text_type):
            data = data.encode("utf-8")

        if self._producerForWrite:
            self._producerForWrite.write(data)
        else:
            self.transport.write(data)

    def writeEncodedSequence(self, sequence):
        encodedSequence = [
            ele if isinstance(ele, bytes) else ele.encode("utf-8")
            for ele in sequence
        ]
        if self._producerForWrite:
            self._producerForWrite.writeSequence(encodedSequence)
        else:
            self.transport.writeSequence(encodedSequence)

    def sendCommonPreamble(self):
        """
        Send the preamble common to all WebSockets connections.

        This might go away in the future if WebSockets continue to diverge.
        """

        self.writeEncodedSequence(
            [
                "HTTP/1.1 101 FYI I am not a webserver\r\n",
                "Server: TwistedWebSocketWrapper/1.0\r\n",
                "Date: %s\r\n" % datetimeToString(),
                "Upgrade: WebSocket\r\n",
                "Connection: Upgrade\r\n",
            ]
        )

    def sendHyBi00Preamble(self):
        """
        Send a HyBi-00 preamble.
        """

        protocol = "wss" if self.isSecure() else "ws"

        self.sendCommonPreamble()

        self.writeEncodedSequence(
            [
                "Sec-WebSocket-Origin: %s\r\n" % self.origin,
                "Sec-WebSocket-Location: %s://%s%s\r\n"
                % (protocol, self.host, self.location),
                "WebSocket-Protocol: %s\r\n" % self.codec,
                "Sec-WebSocket-Protocol: %s\r\n" % self.codec,
                "\r\n",
            ]
        )

    def sendHyBi07Preamble(self):
        """
        Send a HyBi-07 preamble.
        """

        self.sendCommonPreamble()

        if self.codec:
            self.writeEncoded("Sec-WebSocket-Protocol: %s\r\n" % self.codec)

        challenge = self.headers["Sec-WebSocket-Key"]
        response = make_accept(challenge)

        self.writeEncoded("Sec-WebSocket-Accept: %s\r\n\r\n" % response)

    def parseFrames(self):
        """
        Find frames in incoming data and pass them to the underlying protocol.
        """

        if self.flavor == HYBI00:
            parser = parse_hybi00_frames
        elif self.flavor in (HYBI07, HYBI10, RFC6455):
            parser = parse_hybi07_frames
        else:
            raise WSException("Unknown flavor %r" % self.flavor)

        try:
            frames, self.buf = parser(self.buf)
        except WSException as wse:
            # Couldn't parse all the frames, something went wrong, let's bail.
            self.close(wse.args[0])
            return

        for frame in frames:
            opcode, data = frame
            if opcode == NORMAL:
                # Business as usual. Decode the frame, if we have a decoder.
                if self.codec:
                    data = decoders[self.codec](data)
                # Pass the frame to the underlying protocol.
                ProtocolWrapper.dataReceived(self, data)
            elif opcode == CLOSE:
                # The other side wants us to close. I wonder why?
                reason, text = data
                log.msg("Closing connection: %r (%d)" % (text, reason))

                # Close the connection.
                self.close()

    def sendFrames(self):
        """
        Send all pending frames.
        """

        if self.state != FRAMES:
            return

        if self.flavor == HYBI00:
            maker = make_hybi00_frame
        elif self.flavor in (HYBI07, HYBI10, RFC6455):
            if self.do_binary_frames:
                maker = make_hybi07_frame_dwim
            else:
                maker = make_hybi07_frame
        else:
            raise WSException("Unknown flavor %r" % self.flavor)

        for frame in self.pending_frames:
            # Encode the frame before sending it.
            if self.codec:
                frame = encoders[self.codec](frame)
            packets = maker(frame)
            self.writeEncodedSequence(packets)
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
        # reasons I cannot fathom. Newer versions of noVNC (0.4+) sets
        # multiple comma-separated codecs, handle this by chosing first one
        # we can encode/decode.
        protocols = None
        if "WebSocket-Protocol" in self.headers:
            protocols = self.headers["WebSocket-Protocol"]
        elif "Sec-WebSocket-Protocol" in self.headers:
            protocols = self.headers["Sec-WebSocket-Protocol"]

        if isinstance(protocols, six.string_types):
            protocols = [p.strip() for p in protocols.split(",")]

            for protocol in protocols:
                if protocol in encoders or protocol in decoders:
                    log.msg("Using WS protocol %s!" % protocol)
                    self.codec = protocol
                    break

                log.msg("Couldn't handle WS protocol %s!" % protocol)

            if not self.codec:
                return False

        # Start the next phase of the handshake for HyBi-00.
        if is_hybi00(self.headers):
            log.msg("Starting HyBi-00/Hixie-76 handshake")
            self.flavor = HYBI00
            self.state = CHALLENGE

        # Start the next phase of the handshake for HyBi-07+.
        if "Sec-WebSocket-Version" in self.headers:
            version = self.headers["Sec-WebSocket-Version"]
            if version == "7":
                log.msg("Starting HyBi-07 conversation")
                self.sendHyBi07Preamble()
                self.flavor = HYBI07
                self.state = FRAMES
            elif version == "8":
                log.msg("Starting HyBi-10 conversation")
                self.sendHyBi07Preamble()
                self.flavor = HYBI10
                self.state = FRAMES
            elif version == "13":
                log.msg("Starting RFC 6455 conversation")
                self.sendHyBi07Preamble()
                self.flavor = RFC6455
                self.state = FRAMES
            else:
                log.msg("Can't support protocol version %s!" % version)
                return False

        return True

    def _initFromRawData(self):
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
                separator = six.b("\r\n")
                if separator in self.buf:
                    request, chaff, self.buf = self.buf.partition(separator)
                    request = request.decode("utf-8")

                    try:
                        verb, self.location, version = request.split(" ")
                    except ValueError:
                        self.loseConnection()
                    else:
                        self.state = NEGOTIATING

            elif self.state == NEGOTIATING:
                # Check to see if we've got a complete set of headers yet.
                separator = six.b("\r\n\r\n")
                if separator in self.buf:
                    head, chaff, self.buf = self.buf.partition(separator)
                    head = head.decode("utf-8")

                    self.headers = http_headers(head)
                    # Validate headers. This will cause a state change.
                    if not self.validateHeaders():
                        self.loseConnection()

            elif self.state == CHALLENGE:
                # Handle the challenge. This is completely exclusive to
                # HyBi-00/Hixie-76.
                if len(self.buf) >= 8:
                    challenge, self.buf = self.buf[:8], self.buf[8:]
                    challenge = challenge.decode("utf-8")

                    response = complete_hybi00(self.headers, challenge)
                    self.sendHyBi00Preamble()
                    self.writeEncoded(response)
                    log.msg("Completed HyBi-00/Hixie-76 handshake")
                    # We're all finished here; start sending frames.
                    self.state = FRAMES

    def initFromRequest(self, request):
        """Init from Process

        Perform an alternate initialisation of the websocket, using the data from a
        , except it takes its headers from a C{twisted.web.http.Request}

        NOTE: txWS passes it's data to the wrapped protocol as decoded strings.
        This setup method will do the conversions so that wrapped protocols won't notice
        the use of the new upgrade support.

        """
        # Set the location from the request URI
        self.location = request.uri.decode("utf-8")

        # Parse headers from the request
        self.headers = {}
        for key, value in request.requestHeaders.getAllRawHeaders():
            key = key.decode("utf-8")
            key = key.replace("Websocket", "WebSocket")  # ???
            self.headers[key] = value[0].decode("utf-8")

        # Set the initial state for the state machine
        oldstate = None
        self.state = NEGOTIATING

        # Execute the state machine.
        while oldstate != self.state:
            oldstate = self.state

            if self.state == NEGOTIATING:
                # Validate headers. This will cause a state change.
                if not self.validateHeaders():
                    self.loseConnection()

            elif self.state == CHALLENGE:
                # Do nothing, the "_initFromRawData" will sort this out
                pass

        # Tick over dataReceived, it makes a compelling case for processing frames now
        self.dataReceived(b"")

    def dataReceived(self, data):
        self.buf += data

        if self.state != FRAMES:
            self._initFromRawData()

        if self.state == FRAMES:
            self.parseFrames()

        # Kick any pending frames. This is needed because frames might have
        # started piling up early; we can get write()s from our protocol above
        # when they makeConnection() immediately, before our browser client
        # actually sends any data. In those cases, we need to manually kick
        # pending frames.
        if self.pending_frames:
            self.sendFrames()

    def write(self, data):
        """
        Write to the transport.

        This method will only be called by the underlying protocol.
        """

        self.pending_frames.append(data)
        self.sendFrames()

    def writeSequence(self, data):
        """
        Write a sequence of data to the transport.

        This method will only be called by the underlying protocol.
        """

        self.pending_frames.extend(data)
        self.sendFrames()

    def close(self, reason=""):
        """
        Close the connection.

        This includes telling the other side we're closing the connection.

        If the other side didn't signal that the connection is being closed,
        then we might not see their last message, but since their last message
        should, according to the spec, be a simple acknowledgement, it
        shouldn't be a problem.
        """

        # Send a closing frame. It's only polite. (And might keep the browser
        # from hanging.)
        if self.flavor in (HYBI07, HYBI10, RFC6455):
            frames = make_hybi07_frame(reason, opcode=0x8)
            self.writeEncodedSequence(frames)

        self.loseConnection()


class WebSocketFactory(WrappingFactory):
    """
    Factory which wraps another factory to provide WebSockets transports for
    all of its protocols.
    """

    protocol = WebSocketProtocol


class WebSocketUpgradeResource(resource.Resource):
    """Websocket Upgrade Resource

    If this resource is hit, it will attempt to upgrade the connection to a websocket.

    """

    isLeaf = 1

    def __init__(self, websocketFactory):
        """Constructor

        @:param websocketFactory: A factory that will build a WebsocketProtocol (above)
        """
        resource.Resource.__init__(self)
        self._websocketFactory = websocketFactory

    def render(self, request):
        websocketProtocol = self._websocketFactory.buildProtocol(
            request.client.host
        )
        websocketProtocol.makeConnection(request.channel.transport)
        websocketProtocol.initFromRequest(request)
        request.channel.upgradeToWebsocket(websocketProtocol)

        return NOT_DONE_YET


class WebSocketUpgradeHTTPChannel(http.HTTPChannel):
    """Websocket Upgrade HTTP Channel

    This channel allows upgrading of websockets
    """

    _websocketProtocol = None

    def upgradeToWebsocket(self, websocketProtocol):
        """Upgrade to Web Socket

        Upgrade this channel to start using the websocket

        """
        self._websocketProtocol = websocketProtocol

        # Clear out some data we no longer use

        if hasattr(self, "dataBuffer"):
            self.dataBuffer = []

        if hasattr(self, "_dataBuffer"):
            self._dataBuffer = []

        if hasattr(self, "_tempDataBuffer"):
            self._tempDataBuffer = []
            self._tempDataLen = 0

    def dataReceived(self, data):
        # If we're upgraded, only send the data to the websocket
        if self._websocketProtocol:
            self._websocketProtocol.dataReceived(data)
            return

        # This will invoke the render method of resource provided
        http.HTTPChannel.dataReceived(self, data)

    def loseConnection(self):
        # If we have a websocket, loose connection to both
        if self._websocketProtocol:
            self._websocketProtocol.loseConnection()

        http.HTTPChannel.loseConnection(self)
