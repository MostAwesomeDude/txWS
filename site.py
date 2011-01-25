from functools import partial

from twisted.web.resource import Resource
from twisted.python import log

from vncap.protocol import VNCServerAuthenticator
from vncap.websocket import WebSocketSite, WebSocketHandler

class DummyTransport(object):
    buf = ""

    def write(self, data):
        self.buf += data

class VNCHandler(WebSocketHandler):
    """
    A handler that pretends the other side of the connection is VNC over WS.
    """

    def __init__(self, transport, password=""):
        self.password = password

    def connectionMade(self):
        log.msg("Handling request")
        self.protocol = VNCServerAuthenticator(self.password)
        self.protocol.transport = DummyTransport()
        self.protocol.connectionMade()
        self.transport.write(self.protocol.transport.buf)
        self.protocol.transport.buf = ""

    def frameReceived(self, data):
        self.protocol.dataReceived(self, data)
        self.transport.write(self.protocol.transport.buf)
        self.protocol.transport.buf = ""

class VNCSite(WebSocketSite):

    def __init__(self, password):
        handler = partial(VNCHandler, password=password)
        resource = Resource()
        WebSocketSite.__init__(self, resource)
        self.addHandler("/", handler)
