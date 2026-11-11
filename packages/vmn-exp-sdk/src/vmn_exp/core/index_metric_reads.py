#!/usr/bin/env python3
"""The index fold's range reads of metric objects, kept at this path for its
importers. They live in the leaf :mod:`vmn_exp.core.metric_object_reads`, so
the SDK's write path reaches them without importing the index modules."""
from vmn_exp.core.metric_object_reads import MetricObjectGone, object_read, relisted

__all__ = ["MetricObjectGone", "object_read", "relisted"]
