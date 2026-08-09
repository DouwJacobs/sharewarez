# Download delivery

Direct file downloads support HTTP single-byte range requests. Clients can
resume an interrupted transfer by sending `Range: bytes=<offset>-`; successful
partial responses return `206 Partial Content`, `Accept-Ranges: bytes`, an
exact `Content-Range`, and the partial `Content-Length`. Invalid,
unsatisfiable, and multi-range requests return `416` with
`Content-Range: bytes */<file-size>`.

On-demand ZIP streams do not advertise byte-range support. Their output is
generated during each request and therefore has no stable random-access byte
offset. A game represented by one stable file is delivered directly and is
resumable; a multi-file directory is delivered as an on-demand ZIP and must be
restarted if interrupted.

When changing download delivery, preserve the path and ownership checks in
`asgi.py` and run `tests/test_download_ranges.py` plus the download route tests.
