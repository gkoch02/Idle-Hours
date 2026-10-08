"""Tests of the retired ``glacier`` theme, moved verbatim from ``tests/test_render_quote.py``. Not collected."""


# --- methods moved out of shared test classes (indented as in their class) ---
# From class TestDrawTextDithered in tests/test_render_quote.py:
    def test_glacier_diagonal_shards_split_green_and_white(self):
        """``draw_glacier_border``'s diagonal shards (the longest in
        each corner cluster) are painted green and then post-passed to
        ~50% white, so the eye averages green+white into sky-blue at
        panel distance. White and green must both be present inside
        the corner cluster bbox; an all-green result would mean the
        post-pass never fired.
        """
        # Render on a sentinel background that's neither white nor green
        # so post-pass-flipped pixels are distinguishable from the bg.
        image = Image.new("RGB", (800, 480), (1, 2, 3))
        rq.draw_glacier_border(
            image,
            {"text": rq.SPECTRA6["blue"], "accent": rq.SPECTRA6["green"]},
        )
        # Sample a 40×40 box at the top-left corner (the cluster
        # fans out from the inner-frame corner at ~(16, 16) and the
        # longest shard reaches ~(30, 30)).
        pixels = image.load()
        green_count = 0
        white_count = 0
        for y in range(0, 40):
            for x in range(0, 40):
                p = pixels[x, y]
                if p == rq.SPECTRA6["green"]:
                    green_count += 1
                elif p == rq.SPECTRA6["white"]:
                    white_count += 1
        assert green_count > 0 and white_count > 0, (
            f"glacier TL shard must mix green + white (sky-blue post-pass); "
            f"got green={green_count} white={white_count}"
        )
        # The white pixels in this bbox come exclusively from the
        # post-pass flipping accent (green) pixels; assert their layout
        # honours the (x+y)&1 checkerboard, no drift allowed.
        for y in range(0, 40):
            for x in range(0, 40):
                if pixels[x, y] == rq.SPECTRA6["white"]:
                    assert (x + y) & 1 == 0, (
                        f"glacier post-pass flipped a non-checkerboard pixel "
                        f"at ({x}, {y})"
                    )
