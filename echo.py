from twisted.python import log
from sys import stdout
log.startLogging(stdout)

from twisted.internet.protocol import Protocol, Factory
class EchoProtocol(Protocol):
    def dataReceived(self, data):
        self.transport.write(data)

class EchoFactory(Factory):
    protocol = EchoProtocol

from txws import WebSocketFactory
from twisted.application.strports import listen

port = listen("tcp:5600", WebSocketFactory(EchoFactory()))

from twisted.internet import reactor
reactor.run()
