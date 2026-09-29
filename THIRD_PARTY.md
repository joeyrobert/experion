# Third-party software

Experion itself is MIT licensed (see `LICENSE`). The following components keep their own licenses.

| component | where | license |
| --- | --- | --- |
| Fruit 2.1, Fabien Letouzey | `third_party/fruit-2.1` (source, one documented change), served as WebAssembly by the play page | GPL v2 or later |
| CeruleanJS 0.2.0, Joey Robert | `site/engines/ceruleanjs` (web build) | GPL v3 |
| gm2001 opening book, Oliver Deville | `site/engines/ceruleanjs/book.bin`, via ceruleanjs_opening_books | MIT (collection), see its README |
| chess.js, Jeff Hlywa | `site/play/vendor/chess.js` | BSD 2-clause (header in the file) |

Each GPL component sits in its own directory with its license text and the corresponding source, or a
link to it, and is loaded by the web page as a separate program. They are not linked into the Experion
engine.

**Crafty** (Robert Hyatt and others) is deliberately not included. Its license reserves all rights and
does not allow redistribution without the authors' written permission, so the play page cannot serve it.
`tools/engine-bridge.mjs` lets the page drive a Crafty you have installed yourself, on your own computer.
