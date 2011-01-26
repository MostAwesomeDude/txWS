from functools import partial

from twisted.web.resource import Resource
from twisted.python import log

from vncap.protocol import VNCServerAuthenticator
from vncap.websocket import WebSocketSite, WebSocketHandler

class DummyTransport(object):
    buf = ""
    disconnecting = False

    def __init__(self, wrapped):
        self._wrapped_transport = wrapped

    def write(self, data):
        self.buf += data

    def loseConnection(self):
        self._wrapped_transport.loseConnection()

class VNCHandler(WebSocketHandler):
    """
    A handler that pretends the other side of the connection is VNC over WS.

    Specifically, the other side is probably NoVNC, which would like us to
    base64-encode our data.
    """

    def __init__(self, transport, password=""):
        WebSocketHandler.__init__(self, transport)
        self.password = password
        self.dummy = DummyTransport(transport)

    def connectionMade(self):
        log.msg("Handling request")
        self.protocol = VNCServerAuthenticator(self.password)
        self.protocol.makeConnection(self.dummy)
        self.send_framed_data()

    def frameReceived(self, data):
        self.protocol.dataReceived(data.decode("base64"))
        self.send_framed_data()

    def send_framed_data(self):
        self.transport.write(self.dummy.buf.encode("base64"))
        self.dummy.buf = ""

class VNCSite(WebSocketSite):

    def __init__(self, password):
        handler = partial(VNCHandler, password=password)
        resource = Resource()
        WebSocketSite.__init__(self, resource)
        self.addHandler("/", handler)
