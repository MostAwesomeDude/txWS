from twisted.trial import unittest

from twisted.protocols.policies import ProtocolWrapper
from vncap.websocket_new import (WebSocketProtocol, complete_hybi00,
                                 http_headers)

class TestHTTPHeaders(unittest.TestCase):

    def test_single_header(self):
        raw = "Connection: Upgrade"
        headers = http_headers(raw)
        self.assertTrue("Connection" in headers)
        self.assertEqual(headers["Connection"], "Upgrade")

    def test_single_header_newline(self):
        raw = "Connection: Upgrade\n"
        headers = http_headers(raw)
        self.assertEqual(headers["Connection"], "Upgrade")

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

        self.expected = []
        def cb(chaff, data):
            self.expected.append(data)
        self.patch(ProtocolWrapper, "dataReceived", cb)

    def test_trivial(self):
        pass

    def test_parse_frames_single(self):
        frame = "\x00Test\xff"

        self.proto.buf = frame
        self.proto.parse_frames()

        self.assertEqual(len(self.expected), 1)
        self.assertEqual(self.expected[0], "Test")

    def test_parse_frames_multiple(self):
        frame = "\x00Test\xff\x00Again\xff"

        self.proto.buf = frame
        self.proto.parse_frames()

        self.assertEqual(len(self.expected), 2)
        self.assertEqual(self.expected[0], "Test")
        self.assertEqual(self.expected[1], "Again")

    def test_parse_frames_incomplete(self):
        frame = "\x00Test"

        self.proto.buf = frame
        self.proto.parse_frames()

        self.assertEqual(len(self.expected), 0)
