# Change log

## 2026-08-30

- [Net Bookings USD](/metrics/net-bookings-usd.md): documented the allowed
  reporting dimensions (BU, HFM PG Name, Booking Type, KOB Line,
  Interco & Trade, role-specific countries, masked party IDs), per the
  Governed Spec's Metrics catalog and the handoff's query templates. The
  first live agent run showed the omission caused an over-strict refusal
  of an ID-masked "top customer" breakdown that governance actually
  permits.

## 2026-08-24

- Initial serialization of the Averio MEA Bookings semantic layer from the
  v2 governance artifacts (`Averio_Semantic_Layer_Governed_Spec_v2.xlsx`
  and `Averio_Semantic_Layer_AI_Handoff_v2.docx`).
- Seven governed metrics with attested computations; five policies; four
  entities; one governed fact table.
- `computations/cancellation-debookings-usd-fp.md` carries
  `stale_after: 2026-07-31` — already past at serialization time — because
  the Booking Type dictionary (including nonstandard cancellation variants)
  is an open governance item. The date is intentional; it must not be
  advanced until that item closes.
- This bundle replaces the retired Aurora Outdoor pilot bundle; the pilot
  remains available in repository history only.
