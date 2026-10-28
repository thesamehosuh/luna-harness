# Documentation build backport

This is the MIT-licensed CommonJS distribution and type declarations from
`deepmerge@4.3.1`, with its original license retained. The source archive integrity is
`sha512-3sUqbMEc77XqpdNO7FRyRog+eW3ph+GYCbj+rK+uYyRMuwsVy0rMiVtPn+QJlKFvWP/1PYpapqYn0Me2knFn+A==`.

GHSA-gcqx-w48m-w2h4 has no published upstream patch. Both merge loops now reject
`__proto__`, `constructor`, and `prototype` before reading their values. Properties
are created with `Object.defineProperty` rather than invoking inherited setters.
The documented merge API and options stay compatible with the documentation SVG plugin.

The release security gate verifies the patched source hash and runs the regression
tests, in addition to auditing every dependency lock. The website is excluded from
the Luna runtime. Remove this local override when an upstream patch is available.
