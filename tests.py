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
import six
from twisted.trial import unittest

from txwebsocket.txws import (
    is_hybi00,
    complete_hybi00,
    make_hybi00_frame,
    parse_hybi00_frames,
    http_headers,
    make_accept,
    mask,
    CLOSE,
    NORMAL,
    PING,
    PONG,
    parse_hybi07_frames,
)


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


class TestKeys(unittest.TestCase):
    def test_make_accept_rfc(self):
        """
        Test ``make_accept()`` using the keys listed in the RFC for HyBi-07
        through HyBi-10.
        """

        key = "dGhlIHNhbXBsZSBub25jZQ=="

        self.assertEqual(make_accept(key), "s3pPLMBiTxaQ9kYGzzhZRbK+xOo=")

    def test_make_accept_wikipedia(self):
        """
        Test ``make_accept()`` using the keys listed on Wikipedia.
        """

        key = "x3JJHMbDL1EzLkh9GBhXDw=="

        self.assertEqual(make_accept(key), "HSmrc0sMlYUkAGmm5OPpG2HaGWk=")


class TestHyBi00(unittest.TestCase):
    def test_is_hybi00(self):
        headers = {
            "Sec-WebSocket-Key1": "hurp",
            "Sec-WebSocket-Key2": "derp",
        }
        self.assertTrue(is_hybi00(headers))

    def test_is_hybi00_false(self):
        headers = {
            "Sec-WebSocket-Key1": "hurp",
        }
        self.assertFalse(is_hybi00(headers))

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

        self.assertEqual(
            complete_hybi00(headers, challenge), six.b("8jKS'y:G*Co,Wxa-")
        )

    def test_make_hybi00(self):
        """
        HyBi-00 frames are really, *really* simple.
        """

        self.assertEqual(
            b"".join(make_hybi00_frame("Test!")), six.b("\x00Test!\xff")
        )

    def test_parse_hybi00_single(self):
        frame = six.b("\x00Test\xff")

        frames, buf = parse_hybi00_frames(frame)

        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0], (NORMAL, six.b("Test")))
        self.assertEqual(buf, six.b(""))

    def test_parse_hybi00_multiple(self):
        frame = six.b("\x00Test\xff\x00Again\xff")

        frames, buf = parse_hybi00_frames(frame)

        self.assertEqual(len(frames), 2)
        self.assertEqual(frames[0], (NORMAL, six.b("Test")))
        self.assertEqual(frames[1], (NORMAL, six.b("Again")))
        self.assertEqual(buf, six.b(""))

    def test_parse_hybi00_incomplete(self):
        frame = six.b("\x00Test")

        frames, buf = parse_hybi00_frames(frame)

        self.assertEqual(len(frames), 0)
        self.assertEqual(buf, six.b("\x00Test"))

    def test_parse_hybi00_garbage(self):
        frame = six.b("trash\x00Test\xff")

        frames, buf = parse_hybi00_frames(frame)

        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0], (NORMAL, six.b("Test")))
        self.assertEqual(buf, six.b(""))

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
            prepared = b"".join(make_hybi00_frame(frame))
            frames, buf = parse_hybi00_frames(prepared)

            self.assertEqual(len(frames), 1)
            self.assertEqual(frames[0], (NORMAL, frame.encode("utf-8")))
            self.assertEqual(buf, six.b(""))


class TestHyBi07Helpers(unittest.TestCase):
    """
    HyBi-07 is best understood as a large family of helper functions which
    work together, somewhat dysfunctionally, to produce a mediocre
    Thanksgiving every other year.
    """

    def test_mask_noop(self):
        key = six.b("\x00\x00\x00\x00")
        self.assertEqual(mask(six.b("Test"), key), six.b("Test"))

    def test_mask_noop_long(self):
        key = six.b("\x00\x00\x00\x00")
        self.assertEqual(mask(six.b("LongTest"), key), six.b("LongTest"))

    def test_parse_hybi07_unmasked_text(self):
        """
        From HyBi-10, 4.7.
        """

        frame = six.b("\x81\x05Hello")
        frames, buf = parse_hybi07_frames(frame)
        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0], (NORMAL, six.b("Hello")))
        self.assertEqual(buf, six.b(""))

    def test_parse_hybi07_masked_text(self):
        """
        From HyBi-10, 4.7.
        """

        frame = six.b("\x81\x857\xfa!=\x7f\x9fMQX")
        frames, buf = parse_hybi07_frames(frame)
        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0], (NORMAL, six.b("Hello")))
        self.assertEqual(buf, six.b(""))

    def test_parse_hybi07_unmasked_text_fragments(self):
        """
        We don't care about fragments. We are totally unfazed.

        From HyBi-10, 4.7.
        """

        frame = six.b("\x01\x03Hel\x80\x02lo")
        frames, buf = parse_hybi07_frames(frame)
        self.assertEqual(len(frames), 2)
        self.assertEqual(frames[0], (NORMAL, six.b("Hel")))
        self.assertEqual(frames[1], (NORMAL, six.b("lo")))
        self.assertEqual(buf, six.b(""))

    def test_parse_hybi07_ping(self):
        """
        From HyBi-10, 4.7.
        """

        frame = six.b("\x89\x05Hello")
        frames, buf = parse_hybi07_frames(frame)
        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0], (PING, six.b("Hello")))
        self.assertEqual(buf, six.b(""))

    def test_parse_hybi07_pong(self):
        """
        From HyBi-10, 4.7.
        """

        frame = six.b("\x8a\x05Hello")
        frames, buf = parse_hybi07_frames(frame)
        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0], (PONG, six.b("Hello")))
        self.assertEqual(buf, six.b(""))

    def test_parse_hybi07_close_empty(self):
        """
        A HyBi-07 close packet may have no body. In that case, it should use
        the generic error code 1000, and have no reason.
        """

        frame = six.b("\x88\x00")
        frames, buf = parse_hybi07_frames(frame)
        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0], (CLOSE, (1000, six.b("No reason given"))))
        self.assertEqual(buf, six.b(""))

    def test_parse_hybi07_close_reason(self):
        """
        A HyBi-07 close packet must have its first two bytes be a numeric
        error code, and may optionally include trailing text explaining why
        the connection was closed.
        """

        frame = six.b("\x88\x0b\x03\xe8No reason")
        frames, buf = parse_hybi07_frames(frame)
        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0], (CLOSE, (1000, six.b("No reason"))))
        self.assertEqual(buf, six.b(""))

    def test_parse_hybi07_partial_no_length(self):
        frame = six.b("\x81")
        frames, buf = parse_hybi07_frames(frame)
        self.assertFalse(frames)
        self.assertEqual(buf, six.b("\x81"))

    def test_parse_hybi07_partial_truncated_length_int(self):
        frame = six.b("\x81\xfe")
        frames, buf = parse_hybi07_frames(frame)
        self.assertFalse(frames)
        self.assertEqual(buf, six.b("\x81\xfe"))

    def test_parse_hybi07_partial_truncated_length_double(self):
        frame = six.b("\x81\xff")
        frames, buf = parse_hybi07_frames(frame)
        self.assertFalse(frames)
        self.assertEqual(buf, six.b("\x81\xff"))

    def test_parse_hybi07_partial_no_data(self):
        frame = six.b("\x81\x05")
        frames, buf = parse_hybi07_frames(frame)
        self.assertFalse(frames)
        self.assertEqual(buf, six.b("\x81\x05"))

    def test_parse_hybi07_partial_truncated_data(self):
        frame = six.b("\x81\x05Hel")
        frames, buf = parse_hybi07_frames(frame)
        self.assertFalse(frames)
        self.assertEqual(buf, six.b("\x81\x05Hel"))
