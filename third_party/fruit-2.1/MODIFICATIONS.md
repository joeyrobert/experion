# Fruit 2.1 as used by Experion's web player

This directory holds the source of **Fruit 2.1** (Peach) by Fabien Letouzey, released 2005-06-17
under the GNU General Public License, version 2 or (at your option) any later version. See
`copying.txt` and `readme.txt`. The source was taken from the public mirror
https://github.com/Warpten/Fruit-2.1.

It is compiled to WebAssembly for the play page with `tools/build_fruit_wasm.sh` and served as
`site/engines/fruit/fruit.wasm`. Corresponding source for that binary is this directory.

## Modifications

Only one change to the original sources, in `src/posix.cpp`: `input_available()` returns `false`
when compiled for WASI (`__wasi__`). The web player feeds the engine a complete UCI script on
standard input, so there is never input to poll for while searching. Nothing else differs from the
original distribution (the object files, executables and opening book were not copied).
