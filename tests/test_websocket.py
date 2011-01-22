# Copyright (c) 2009 Twisted Matrix Laboratories.
# See LICENSE for details.

"""
Tests for L{twisted.web.websocket}.
"""

from twisted.internet.main import CONNECTION_DONE
from twisted.internet.error import ConnectionDone
from twisted.python.failure import Failure

from vncap.websocket import WebSocketHandler, WebSocketFrameDecoder
from vncap.websocket import WebSocketSite, WebSocketTransport

from twisted.web.resource import Resource
from twisted.web.server import Request
from twisted.web.test.test_web import DummyChannel
from twisted.trial.unittest import TestCase



class DummyChannel(DummyChannel):
    """
    A L{DummyChannel} supporting the C{setRawMode} method.

    @ivar raw: C{bool} indicating if C{setRawMode} has been called.
    """

    raw = False

    def setRawMode(self):
        self.raw = True



class TestHandler(WebSocketHandler):
    """
    A L{WebSocketHandler} recording every frame received.

    @ivar frames: C{list} of frames received.
    @ivar lostReason: reason for connection closing.
    """

    def __init__(self, request):
        WebSocketHandler.__init__(self, request)
        self.frames = []
        self.lostReason = None


    def frameReceived(self, frame):
        self.frames.append(frame)


    def connectionLost(self, reason):
        self.lostReason = reason



class WebSocketSiteTestCase(TestCase):
    """
    Tests for L{WebSocketSite}.
    """

    def setUp(self):
        self.site = WebSocketSite(Resource())
        self.site.addHandler("/test", TestHandler)


    def renderRequest(self, headers=None, url="/test", ssl=False,
                      queued=False, body=None):
        """
        Render a request against C{self.site}, writing the WebSocket
        handshake.
        """
        if headers is None:
            headers = [
                ("Upgrade", "WebSocket"), ("Connection", "Upgrade"),
                ("Host", "localhost"), ("Origin", "http://localhost/")]
        channel = DummyChannel()
        if ssl:
            channel.transport = channel.SSL()
        channel.site = self.site
        request = self.site.requestFactory(channel, queued)
        for k, v in headers:
            request.requestHeaders.addRawHeader(k, v)
        request.gotLength(0)
        request.requestReceived("GET", url, "HTTP/1.1")
        if body:
            request.channel._transferDecoder.finishCallback(body)
        return channel


    def test_multiplePostpath(self):
        """
        A resource name can consist of several path elements.
        """
        handlers = []
        def handlerFactory(request):
            handler = TestHandler(request)
            handlers.append(handler)
            return handler
        self.site.addHandler("/foo/bar", handlerFactory)
        channel = self.renderRequest(url="/foo/bar")
        self.assertEquals(len(handlers), 1)
        self.assertFalse(channel.transport.disconnected)


    def test_queryArguments(self):
        """
        A resource name may contain query arguments.
        """
        handlers = []
        def handlerFactory(request):
            handler = TestHandler(request)
            handlers.append(handler)
            return handler
        self.site.addHandler("/test?foo=bar&egg=spam", handlerFactory)
        channel = self.renderRequest(url="/test?foo=bar&egg=spam")
        self.assertEquals(len(handlers), 1)
        self.assertFalse(channel.transport.disconnected)


    def test_noOriginHeader(self):
        """
        If no I{Origin} header is present, the connection is closed.
        """
        channel = self.renderRequest(
            headers=[("Upgrade", "WebSocket"), ("Connection", "Upgrade"),
                     ("Host", "localhost")])
        self.assertFalse(channel.transport.written.getvalue())
        self.assertTrue(channel.transport.disconnected)


    def test_multipleOriginHeaders(self):
        """
        If more than one I{Origin} header is present, the connection is
        dropped.
        """
        channel = self.renderRequest(
            headers=[("Upgrade", "WebSocket"), ("Connection", "Upgrade"),
                     ("Host", "localhost"), ("Origin", "foo"),
                     ("Origin", "bar")])
        self.assertFalse(channel.transport.written.getvalue())
        self.assertTrue(channel.transport.disconnected)


    def test_noHostHeader(self):
        """
        If no I{Host} header is present, the connection is dropped.
        """
        channel = self.renderRequest(
            headers=[("Upgrade", "WebSocket"), ("Connection", "Upgrade"),
                     ("Origin", "http://localhost/")])
        self.assertFalse(channel.transport.written.getvalue())
        self.assertTrue(channel.transport.disconnected)


    def test_multipleHostHeaders(self):
        """
        If more than one I{Host} header is present, the connection is
        dropped.
        """
        channel = self.renderRequest(
            headers=[("Upgrade", "WebSocket"), ("Connection", "Upgrade"),
                     ("Origin", "http://localhost/"), ("Host", "foo"),
                     ("Host", "bar")])
        self.assertFalse(channel.transport.written.getvalue())
        self.assertTrue(channel.transport.disconnected)


    def test_missingHandler(self):
        """
        If no handler is registered for the given resource, the connection is
        dropped.
        """
        channel = self.renderRequest(url="/foo")
        self.assertFalse(channel.transport.written.getvalue())
        self.assertTrue(channel.transport.disconnected)


    def test_noConnectionUpgrade(self):
        """
        If the I{Connection: Upgrade} header is not present, the connection is
        dropped.
        """
        channel = self.renderRequest(
            headers=[("Upgrade", "WebSocket"), ("Host", "localhost"),
                     ("Origin", "http://localhost/")])
        self.assertIn("404 Not Found", channel.transport.written.getvalue())


    def test_noUpgradeWebSocket(self):
        """
        If the I{Upgrade: WebSocket} header is not present, the connection is
        dropped.
        """
        channel = self.renderRequest(
            headers=[("Connection", "Upgrade"), ("Host", "localhost"),
                     ("Origin", "http://localhost/")])
        self.assertIn("404 Not Found", channel.transport.written.getvalue())


    def test_render(self):
        """
        If the handshake is successful, we can read back the server handshake,
        and the channel is setup for raw mode.
        """
        channel = self.renderRequest()
        self.assertTrue(channel.raw)
        self.assertEquals(
            channel.transport.written.getvalue(),
            "HTTP/1.1 101 Web Socket Protocol Handshake\r\n"
            "Upgrade: WebSocket\r\n"
            "Connection: Upgrade\r\n"
            "WebSocket-Origin: http://localhost/\r\n"
            "WebSocket-Location: ws://localhost/test\r\n\r\n")
        self.assertFalse(channel.transport.disconnected)

    def test_render_handShake76(self):
        """
        Test a hixie-76 handShake.
        """
        # we need to construct a challenge
        key1 = '1x0x0 0y00 0'  # 1000000
        key2 = '1b0b0 000 0'   # 1000000
        body = '12345678'
        headers = [
            ("Upgrade", "WebSocket"), ("Connection", "Upgrade"),
            ("Host", "localhost"), ("Origin", "http://localhost/"),
            ("Sec-WebSocket-Key1", key1), ("Sec-WebSocket-Key2", key2)]
        channel = self.renderRequest(headers=headers, body=body)

        self.assertTrue(channel.raw)

        result = channel.transport.written.getvalue()

        headers, response = result.split('\r\n\r\n')

        self.assertEquals(
            headers,
            "HTTP/1.1 101 Web Socket Protocol Handshake\r\n"
            "Upgrade: WebSocket\r\n"
            "Connection: Upgrade\r\n"
            "Sec-WebSocket-Origin: http://localhost/\r\n"
            "Sec-WebSocket-Location: ws://localhost/test")

        # check challenge is correct
        from hashlib import md5
        import struct
        self.assertEquals(md5(struct.pack('>ii8s', 500000, 500000, body)).digest(), response)

        self.assertFalse(channel.transport.disconnected)

    def test_secureRender(self):
        """
        If the WebSocket connection is over SSL, the I{WebSocket-Location}
        header specified I{wss} as scheme.
        """
        channel = self.renderRequest(ssl=True)
        self.assertTrue(channel.raw)
        self.assertEquals(
            channel.transport.written.getvalue(),
            "HTTP/1.1 101 Web Socket Protocol Handshake\r\n"
            "Upgrade: WebSocket\r\n"
            "Connection: Upgrade\r\n"
            "WebSocket-Origin: http://localhost/\r\n"
            "WebSocket-Location: wss://localhost/test\r\n\r\n")
        self.assertFalse(channel.transport.disconnected)


    def test_frameReceived(self):
        """
        C{frameReceived} is called with the received frames after handshake.
        """
        handlers = []
        def handlerFactory(request):
            handler = TestHandler(request)
            handlers.append(handler)
            return handler
        self.site.addHandler("/test2", handlerFactory)
        channel = self.renderRequest(url="/test2")
        self.assertEquals(len(handlers), 1)
        handler = handlers[0]
        channel._transferDecoder.dataReceived("\x00hello\xff\x00boy\xff")
        self.assertEquals(handler.frames, ["hello", "boy"])


    def test_websocketProtocolAccepted(self):
        """
        The I{WebSocket-Protocol} header is echoed by the server if the
        protocol is among the supported protocols.
        """
        self.site.supportedProtocols.append("pixiedust")
        channel = self.renderRequest(
            headers = [
            ("Upgrade", "WebSocket"), ("Connection", "Upgrade"),
            ("Host", "localhost"), ("Origin", "http://localhost/"),
            ("WebSocket-Protocol", "pixiedust")])
        self.assertTrue(channel.raw)
        self.assertEquals(
            channel.transport.written.getvalue(),
            "HTTP/1.1 101 Web Socket Protocol Handshake\r\n"
            "Upgrade: WebSocket\r\n"
            "Connection: Upgrade\r\n"
            "WebSocket-Origin: http://localhost/\r\n"
            "WebSocket-Location: ws://localhost/test\r\n"
            "WebSocket-Protocol: pixiedust\r\n\r\n")
        self.assertFalse(channel.transport.disconnected)


    def test_tooManyWebSocketProtocol(self):
        """
        If more than one I{WebSocket-Protocol} headers are specified, the
        connection is dropped.
        """
        self.site.supportedProtocols.append("pixiedust")
        channel = self.renderRequest(
            headers = [
            ("Upgrade", "WebSocket"), ("Connection", "Upgrade"),
            ("Host", "localhost"), ("Origin", "http://localhost/"),
            ("WebSocket-Protocol", "pixiedust"),
            ("WebSocket-Protocol", "fairymagic")])
        self.assertFalse(channel.transport.written.getvalue())
        self.assertTrue(channel.transport.disconnected)


    def test_unsupportedProtocols(self):
        """
        If the I{WebSocket-Protocol} header specified an unsupported protocol,
        the connection is dropped.
        """
        self.site.supportedProtocols.append("pixiedust")
        channel = self.renderRequest(
            headers = [
            ("Upgrade", "WebSocket"), ("Connection", "Upgrade"),
            ("Host", "localhost"), ("Origin", "http://localhost/"),
            ("WebSocket-Protocol", "fairymagic")])
        self.assertFalse(channel.transport.written.getvalue())
        self.assertTrue(channel.transport.disconnected)


    def test_queued(self):
        """
        Queued requests are unsupported, thus closed by the
        C{WebSocketSite}.
        """
        channel = self.renderRequest(queued=True)
        self.assertFalse(channel.transport.written.getvalue())
        self.assertTrue(channel.transport.disconnected)


    def test_addHandlerWithoutSlash(self):
        """
        C{addHandler} raises C{ValueError} if the resource name doesn't start
        with a slash.
        """
        self.assertRaises(
            ValueError, self.site.addHandler, "test", TestHandler)



class WebSocketFrameDecoderTestCase(TestCase):
    """
    Test for C{WebSocketFrameDecoder}.
    """

    def setUp(self):
        self.channel = DummyChannel()
        request = Request(self.channel, False)
        transport = WebSocketTransport(request)
        handler = TestHandler(transport)
        transport._attachHandler(handler)
        self.decoder = WebSocketFrameDecoder(request, handler)
        self.decoder.MAX_LENGTH = 100


    def test_oneFrame(self):
        """
        We can send one frame handled with one C{dataReceived} call.
        """
        self.decoder.dataReceived("\x00frame\xff")
        self.assertEquals(self.decoder.handler.frames, ["frame"])


    def test_oneFrameSplitted(self):
        """
        A frame can be split into several C{dataReceived} calls, and will be
        combined again when sent to the C{WebSocketHandler}.
        """
        self.decoder.dataReceived("\x00fra")
        self.decoder.dataReceived("me\xff")
        self.assertEquals(self.decoder.handler.frames, ["frame"])


    def test_multipleFrames(self):
        """
        Several frames can be received in a single C{dataReceived} call.
        """
        self.decoder.dataReceived("\x00frame1\xff\x00frame2\xff")
        self.assertEquals(self.decoder.handler.frames, ["frame1", "frame2"])


    def test_missingNull(self):
        """
        If a frame not starting with C{\\x00} is received, the connection is
        dropped.
        """
        self.decoder.dataReceived("frame\xff")
        self.assertTrue(self.channel.transport.disconnected)


    def test_missingNullAfterGoodFrame(self):
        """
        If a frame not starting with C{\\x00} is received after a correct
        frame, the connection is dropped.
        """
        self.decoder.dataReceived("\x00frame\xfffoo")
        self.assertTrue(self.channel.transport.disconnected)
        self.assertEquals(self.decoder.handler.frames, ["frame"])


    def test_emptyReceive(self):
        """
        Received an empty string doesn't do anything.
        """
        self.decoder.dataReceived("")
        self.assertFalse(self.channel.transport.disconnected)


    def test_maxLength(self):
        """
        If a frame is received which is bigger than C{MAX_LENGTH}, the
        connection is dropped.
        """
        self.decoder.dataReceived("\x00" + "x" * 101)
        self.assertTrue(self.channel.transport.disconnected)


    def test_maxLengthFrameCompleted(self):
        """
        If a too big frame is received in several fragments, the connection is
        dropped.
        """
        self.decoder.dataReceived("\x00" + "x" * 90)
        self.decoder.dataReceived("x" * 11 + "\xff")
        self.assertTrue(self.channel.transport.disconnected)


    def test_frameLengthReset(self):
        """
        The length of frames is reset between frame, thus not creating an error
        when the accumulated length exceeds the maximum frame length.
        """
        for i in range(15):
            self.decoder.dataReceived("\x00" + "x" * 10 + "\xff")
        self.assertFalse(self.channel.transport.disconnected)



class WebSocketHandlerTestCase(TestCase):
    """
    Tests for L{WebSocketHandler}.
    """

    def setUp(self):
        self.channel = DummyChannel()
        self.request = request = Request(self.channel, False)
        # Simulate request handling
        request.startedWriting = True
        transport = WebSocketTransport(request)
        self.handler = TestHandler(transport)
        transport._attachHandler(self.handler)


    def test_write(self):
        """
        L{WebSocketTransport.write} adds the required C{\\x00} and C{\\xff}
        around sent frames, and write it to the request.
        """
        self.handler.transport.write("hello")
        self.handler.transport.write("world")
        self.assertEquals(
            self.channel.transport.written.getvalue(),
            "\x00hello\xff\x00world\xff")
        self.assertFalse(self.channel.transport.disconnected)


    def test_close(self):
        """
        L{WebSocketTransport.loseConnection} closes the underlying request.
        """
        self.handler.transport.loseConnection()
        self.assertTrue(self.channel.transport.disconnected)


    def test_connectionLost(self):
        """
        L{WebSocketHandler.connectionLost} is called with the reason of the
        connection closing when L{Request.connectionLost} is called.
        """
        self.request.connectionLost(Failure(CONNECTION_DONE))
        self.handler.lostReason.trap(ConnectionDone)
