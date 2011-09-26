====
txWS
====

txWS (prounounced "Twisted WebSockets") is a small, short, simple library for
adding WebSockets support to your favorite Twisted applications.

Usage
=====

Use ``txws.WebSocketFactory`` to wrap your factories. That's it! Adding
WebSockets support has never been easier.

    from txws import WebSocketFactory
    reactor.listenTCP(8080, WebSocketFactory(factory_to_wrap)

Versions
========

txWS supports the following versions of the WebSockets draft:

 * Version 76
   * Hixie-76
   * HyBi-00
 * Version 7
   * HyBi-07
