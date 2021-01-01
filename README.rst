============
txWS Upgrade
============

txWS-Upgrade (pronounced "Twisted WebSockets Upgrade") is a small, short, simple library for
adding WebSockets server support to your favorite Twisted applications.

This is forked from txWS to add upgrade support.
https://github.com/MostAwesomeDude/txWS


Usage
=====

Use ``txwebsocket.txws.WebSocketFactory`` to wrap your factories. That's it! Adding
WebSockets support has never been easier.

    >>> from txwebsocket.txws import WebSocketFactory
    >>> reactor.listenTCP(8080, WebSocketFactory(factory_to_wrap))

There is no extra trick to txWS. There is no special setup involved.

Do you want secure WebSockets? Use ``listenSSL()`` instead of ``listenTCP()``.

Upgrade Usage
=============

If you want to use the websocket with in an existing site, Update your code as follows.

This is a vanilla Twisted website. ::


        from twisted.web import server
        from twisted.web.resource import Resource
        from twisted.internet import reactor, endpoints

        class Simple(Resource):
            isLeaf = True
            def getChild(self, name, request):
                if name == '':
                    return self
                return Resource.getChild(self, name, request)

            def render_GET(self, request):
                return "Hello, world! I am located at %r." % (request.prepath,)

        rootResource = Simple()
        site = server.Site(rootResource)

        endpoint = endpoints.TCP4ServerEndpoint(reactor, 8080)
        endpoint.listen(site)
        reactor.run()



Now add the website has support for WebSockets, to include
 the ``txwebsocket.txws.WebSocketUpgradeResource`` and ``txwebsocket.txws.WebSocketUpgradeHTTPChannel``. ::

        from twisted.web import server
        from twisted.web.resource import Resource
        from twisted.internet import reactor, endpoints

        class Simple(Resource):
            isLeaf = True
            def getChild(self, name, request):
                if name == '':
                    return self
                return Resource.getChild(self, name, request)

            def render_GET(self, request):
                return "Hello, world! I am located at %r." % (request.prepath,)

        rootResource = Simple()
        site = server.Site(rootResource)

        # 1) Add the imports
        #    Create the WebSocketFactory
        #    Create the WebSocketUpgradeResource
        #    Put the resource into the resource tree
        from txwebsocket.txws import WebSocketFactory, WebSocketUpgradeResource
        rootResource.putChild(b"websocket",
                              WebSocketUpgradeResource(WebSocketFactory(factory_to_wrap)))


        # 2) Add the imports
        #    Replace protocol for the website with the Websocket upgradable ones
        from txwebsocket.txws import WebSocketUpgradeHTTPChannel
        site.protocol = VortexWebsocketHTTPChannel

        endpoint = endpoints.TCP4ServerEndpoint(reactor, 8080)
        endpoint.listen(site)
        reactor.run()


Versions
========

txWS supports the following versions of the WebSockets draft:

 * Version 76

   * Hixie-76 (Chrome 6, Fx 4, Opera 11, **UNTESTED** Safari 5)
   * HyBi-00

 * Version 7

   * HyBi-07 (Fx 6)

 * Version 8

   * HyBi-08
   * HyBi-10 (Chrome 14, Chrome 15, Fx 7, Fx 8)

 * Version 13

   * RFC 6455 (Chrome 16)

All listed browser versions have been tested and verified working; any browser
marked "UNTESTED" hasn't been personally tested, but has been reported working
by third parties.

In case you're wondering, the version numbers above are correct; WebSockets
versioning is not sane.

Browser Quirks
==============

This might save you some time when developing your WebSockets-based
application.

 * Firefox (all versions): WebSockets do not follow the standard WebSocket
   API.
 * Opera 11: WebSockets are disabled by default and are very slow to close
   connections.

Comparisons
===========

Here's how txWS compares to other Twisted WebSockets libraries.

txWebSockets
------------

txWS, unlike txWebSockets, doesn't reuse any HTTP machinery and doesn't
pretend to be HTTP. Whether this is a good or bad thing depends largely on
whether the WebSockets standard ends up being a valid HTTP subset.

txWS supports newer WS versions 7 and 8, but txWebSockets supports the older
version 75. Both libraries support version 76.

Autobahn
--------

Autobahn provides a client library for WebSockets as well as a server, and
provides a fancy set of messaging protocols on top of the WS layer. Autobahn
also provides support for WS version 10.

However, Autobahn doesn't provide support for WS version 76, and requires
clients to subclass their factories and protocols in order to provide WS
functionality. txWS uses a compositional approach with wrapped protocols,
allowing completely transparent reuse of existing protocols and factories.

Cyclone
-------

Cyclone provides a simple WebSockets handler. This handler can do WS versions
75 and 76. The Cyclone WebSockets handler is very limited, can only wrap other
Cyclone handlers, and doesn't support any of the more modern WebSockets
versions.

License
=======

txWS is (c) 2011 Oregon State University Open Source Lab, (c) 2014 Google
Inc., and is made available under the Apache 2.0 license.

Thanks
======

Thank you to all of the contributors in the community who have chipped in to
help keep txWS alive.
