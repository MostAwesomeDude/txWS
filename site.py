from functools import partial

from twisted.web.resource import Resource
from twisted.protocols.policies import ProtocolWrapper
from twisted.python import log

from vncap.protocol import VNCServerAuthenticator
from vncap.websocket import WebSocketSite, WebSocketHandler

class DummyFactory(object):
    """
    A shim to fool ProtocolWrapper.

    We don't actually care about the wrapper factory functionality, so.
    """

    def registerProtocol(self, protocol):
        pass

    def unregisterProtocol(self, protocol):
        pass

class Base64Transport(ProtocolWrapper):

    def dataReceived(self, data):
        ProtocolWrapper.dataReceived(self, data.decode("base64"))

    def write(self, data):
        ProtocolWrapper.write(self, data.encode("base64"))

    def writeSequence(self, data):
        ProtocolWrapper.writeSequence(self,
            [i.encode("base64") for i in data])

class VNCHandler(WebSocketHandler):
    """
    A handler that pretends the other side of the connection is VNC over WS.

    Specifically, the other side is probably NoVNC, which would like us to
    base64-encode our data.
    """

    def __init__(self, transport, password=""):
        WebSocketHandler.__init__(self, transport)
        self.wrapped = Base64Transport(DummyFactory(),
            VNCServerAuthenticator(password))
        self.transport = transport

    def connectionMade(self):
        self.wrapped.makeConnection(self.transport)

    def frameReceived(self, data):
        self.wrapped.dataReceived(data)

class VNCSite(WebSocketSite):

    def __init__(self, password):
        handler = partial(VNCHandler, password=password)
        resource = Resource()
        WebSocketSite.__init__(self, resource)
        self.addHandler("/", handler)
