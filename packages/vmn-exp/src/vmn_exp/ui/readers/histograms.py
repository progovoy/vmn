#!/usr/bin/env python3
"""A run's logged histograms for the ui API: one name's served steps at a time.

A watched model logs a histogram key per parameter tensor (hundreds of keys,
up to :data:`~vmn_exp.core.media.MAX_HISTOGRAM_STEPS` served steps each), so
the run detail carries ``histograms_total`` (every name, its steps logged)
and inlines the steps in ``histograms`` only while they are few; a client
asks for each name it shows (:func:`histogram_of`).
"""

# Served steps (across names) a detail still inlines: one full key's worth.
INLINE_HISTOGRAM_ITEMS = 100


def detail_media(media):
    """The media view for a run detail, histogram steps dropped when many."""
    served = sum(len(items) for items in media["histograms"].values())
    if served <= INLINE_HISTOGRAM_ITEMS:
        return media
    return {**media, "histograms": {}}


def histogram_of(media, name):
    """``{"name", "steps", "total"}`` of histogram *name* in a media view, or
    None when the run logged no such histogram."""
    steps = media["histograms"].get(name)
    if steps is None:
        return None
    return {"name": name, "steps": steps, "total": media["histograms_total"][name]}
