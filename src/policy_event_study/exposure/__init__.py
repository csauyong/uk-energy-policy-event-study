"""Firm-level policy exposure: the project's core contribution.

The dose-response design identifies from cross-sectional variation in exposure
across the whole listed universe rather than from a handful of treated units.
That makes the exposure measure the load-bearing input, and it has no
off-the-shelf substitute -- a sector dummy would throw away exactly the
variation the design runs on.

`schema.py` defines the curated inputs and the point-in-time filter,
`channels.py` maps disclosures to a dose in [0, 1], `build.py` assembles the
firm x event panel and standardises within event.

See docs/exposure_construction.md for every judgement call and its
sensitivity. That document is a deliverable in its own right: it is the part
of the project a reader cannot reproduce from public method descriptions.
"""
