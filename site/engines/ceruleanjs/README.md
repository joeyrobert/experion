# CeruleanJS (web build)

CeruleanJS 0.2.0, a JavaScript chess engine by Joey Robert, licensed under the GNU General
Public License version 3 (see `LICENSE`). `ceruleanjs.js` is the browserified, minified web worker
built from the sources at https://bitbucket.org/joeyrobert/ceruleanjs (commit `55d77be`) with
`npm run build-web`. It speaks the XBoard protocol over `postMessage`.

`book.bin` is the `gm2001` Polyglot opening book (games from 2001 to 2013 by players rated 2530+,
compiled by Oliver Deville), taken from https://github.com/joeyrobert/ceruleanjs_opening_books
(MIT licensed collection, copied from the Donna chess engine's books).
