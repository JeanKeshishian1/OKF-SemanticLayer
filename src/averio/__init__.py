"""Harness for the Averio MEA Bookings semantic-layer capstone.

This package is the *experiment harness*, not the deliverable: it builds the
synthetic bookings dataset, derives the eval answer key, and holds the
sanctioned SQL that the OKF bundle mirrors. The deliverable is the semantic
layer itself (see `bundle/`) and its measured effect on agent behavior.

Modules
-------
fiscal          Averio fiscal calendar (Oct 1 - Sep 30, FY named for end year).
sanctioned_sql  Governed metric SQL (single source of truth) + naive variants.
generate_data   Seeded synthetic generator -> DuckDB + eval/ground_truth.json.
"""
