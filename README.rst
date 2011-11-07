====
txWS
====

txWS (prounounced "Twisted WebSockets") is a small, short, simple library for
adding WebSockets support to your favorite Twisted applications.

Usage
=====

Use ``txws.WebSocketFactory`` to wrap your factories. That's it! Adding
WebSockets support has never been easier.

    >>> from txws import WebSocketFactory
    >>> reactor.listenTCP(8080, WebSocketFactory(factory_to_wrap))

There is no extra trick to txWS. There is no special setup involved.

Do you want secure WebSockets? Use ``listenSSL()`` instead of ``listenTCP()``.

Versions
========

txWS supports the following versions of the WebSockets draft:

 * Version 76

   * Hixie-76
   * HyBi-00

 * Version 7

   * HyBi-07

 * Version 8

   * HyBi-08

In case you're wondering, the version numbers above are correct; WebSockets
versioning is not sane.

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
