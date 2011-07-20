from twisted.trial import unittest

from twisted.protocols.policies import ProtocolWrapper
from vncap.websocket import (WebSocketProtocol, complete_hybi00, http_headers,
                             FRAMES)

class TestHTTPHeaders(unittest.TestCase):

    def test_single_header(self):
        raw = "Connection: Upgrade"
        headers = http_headers(raw)
        self.assertTrue("Connection" in headers)
        self.assertEqual(headers["Connection"], "Upgrade")

    def test_single_header_newline(self):
        raw = "Connection: Upgrade\r\n"
        headers = http_headers(raw)
        self.assertEqual(headers["Connection"], "Upgrade")

    def test_multiple_headers(self):
        raw = "Connection: Upgrade\r\nUpgrade: WebSocket"
        headers = http_headers(raw)
        self.assertEqual(headers["Connection"], "Upgrade")
        self.assertEqual(headers["Upgrade"], "WebSocket")

    def test_origin_colon(self):
        """
        Some headers have multiple colons in them.
        """

        raw = "Origin: http://example.com:8080"
        headers = http_headers(raw)
        self.assertEqual(headers["Origin"], "http://example.com:8080")

class TestHyBi00(unittest.TestCase):

    def test_complete_hybi00_wikipedia(self):
        """
        Test complete_hybi00() using the keys listed on Wikipedia's WebSockets
        page.
        """

        headers = {
            "Sec-WebSocket-Key1": "4 @1  46546xW%0l 1 5",
            "Sec-WebSocket-Key2": "12998 5 Y3 1  .P00",
        }
        challenge = "^n:ds[4U"

        self.assertEqual(complete_hybi00(headers, challenge),
                         "8jKS'y:G*Co,Wxa-")

class TestWebSocketProtocolFrames(unittest.TestCase):

    def setUp(self):
        self.proto = WebSocketProtocol(None, None)
        self.proto.state = FRAMES

        self.expected = []
        def dr(chaff, data):
            self.expected.append(data)
        self.patch(ProtocolWrapper, "dataReceived", dr)

        self.sent = []
        class FakeTransport:
            def write(chaff, data):
                self.sent.append(data)
        self.proto.transport = FakeTransport()

    def test_trivial(self):
        pass

    def test_parseFrames_single(self):
        frame = "\x00Test\xff"

        self.proto.buf = frame
        self.proto.parseFrames()

        self.assertEqual(len(self.expected), 1)
        self.assertEqual(self.expected[0], "Test")

    def test_parseFrames_multiple(self):
        frame = "\x00Test\xff\x00Again\xff"

        self.proto.buf = frame
        self.proto.parseFrames()

        self.assertEqual(len(self.expected), 2)
        self.assertEqual(self.expected[0], "Test")
        self.assertEqual(self.expected[1], "Again")

    def test_parseFrames_incomplete(self):
        frame = "\x00Test"

        self.proto.buf = frame
        self.proto.parseFrames()

        self.assertEqual(len(self.expected), 0)

    def test_parseFrames_garbage(self):
        frame = "trash\x00Test\xff"

        self.proto.buf = frame
        self.proto.parseFrames()

        self.assertEqual(len(self.expected), 1)
        self.assertEqual(self.expected[0], "Test")

    def test_sendFrames_multiple(self):
        self.proto.pending_frames.append("hello")
        self.proto.pending_frames.append("world")

        self.proto.sendFrames()
        self.assertEqual(len(self.sent), 2)
        self.assertEqual(self.sent[0], "\x00hello\xff")
        self.assertEqual(self.sent[1], "\x00world\xff")

    def test_socketio_crashers(self):
        """
        A series of snippets which crash other WebSockets implementations
        (specifically, Socket.IO) are harmless to this implementation.
        """

        frames = [
            """[{"length":1}]""",
            """{"messages":[{"length":1}]}""",
            "hello",
            "hello<script>alert(/xss/)</script>",
            "hello<img src=x:x onerror=alert(/xss.2/)>",
            "{",
            "~m~EVJLFDJP~",
        ]

        for frame in frames:
            self.proto.dataReceived("\x00%s\xff" % frame)
            self.assertEqual(len(self.expected), 1)
            self.assertEqual(self.expected[0], frame)

            self.expected.pop()
