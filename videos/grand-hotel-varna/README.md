# Grand Hotel Varna - "for sale" presentation videos

Six videos (five presentation variations plus a 30-second "why buy now" piece) presenting Grand Hotel Varna (St. Constantine & Helena
resort, Varna, Bulgaria) to prospective buyers. Everything is generated from
`hotel_facts.json` by `render.py`, so copy, numbers and contact details can be
changed in one place and re-rendered.

## The videos

| # | File | Format | Length | Tone / use |
|---|------|--------|--------|------------|
| 1 | `output/01_cinematic_teaser.mp4` | 1920x1080, 30 fps | ~44 s | Dark, gold, slow. Investor teaser for email / data-room landing page. |
| 2 | `output/02_investor_deck.mp4` | 1920x1080, 30 fps | ~35 s | Clean, numeric. Animated room-inventory chart, revenue streams, 2023 public transaction as market context. |
| 3 | `output/03_vertical_reel.mp4` | 1080x1920, 30 fps | ~27 s | Fast-cut vertical reel for Instagram / TikTok / Shorts with pulse soundtrack. |
| 4 | `output/04_lifestyle_story.mp4` | 1920x1080, 30 fps | ~36 s | Warm "a day at the resort" narrative: spa, pools and park, dining and marina. |
| 5 | `output/05_square_linkedin.mp4` | 1080x1080, 30 fps | ~22 s | Square post for LinkedIn / Facebook, location and connectivity led, "why now" list. |
| 6 | `output/06_why_buy_now.mp4` | 1920x1080, 30 fps | ~30 s | Urgency piece: five numbered reasons to buy immediately (scale, 2023 institutional deal, year-round revenue, resort momentum, trading from day one). Red accent, pulse soundtrack. |

All six end with the call to action from `hotel_facts.json` (`cta`) and the
`contact` line. Each has a procedurally generated ambient soundtrack (no
licensed music).

## Re-rendering

```bash
pip install pillow numpy imageio-ffmpeg
python3 render.py              # all six, full quality (~10-15 min on 4 cores)
python3 render.py --preview    # fast 640 px / 12 fps check
python3 render.py --only 3 5   # selected variations
python3 render.py --no-audio
```

## Using real photographs

The backdrops in the current renders are stylised illustrations of the
resort (sea horizon, hotel facade, marina, spa, schematic map). They are
marked "Indicative visuals" in the corner of the 16:9 renders.

Drop real photographs into `photos/` (`.jpg` or `.png`) and re-run
`render.py`. Photos are used as backdrops in filename order, cycling if
there are fewer photos than scenes, with the same Ken Burns motion and text
overlays. The watermark is removed automatically when photos are used.

## Facts and sources

Every figure in the videos comes from public listings and press coverage
collected on 2026-09-03 and stored in `hotel_facts.json`:

- 5-star resort hotel in St. Constantine & Helena, Bulgaria's oldest Black
  Sea resort, 200 m from the beach, 7 km from Varna, 20 km from Varna Airport.
- Flagship: 300 double rooms, 30 suites, 11 storeys.
- Complex: 1,048 rooms and 98 apartments across five hotels (Grand Hotel
  Varna 5*, Dolphin, Dolphin Marina, Rubin, Lebed 4*), yacht marina.
- 6 restaurants, lobby bar, day bar, sky bar, Viennese cafe.
- Spa on hot mineral springs, indoor mineral-water pool, outdoor pool,
  balneo and physiotherapy, sauna and solarium.
- Conference halls for 20 to 220 delegates.
- Market context: in November 2023 Black Sea Property agreed to buy a
  98.27% stake for approx. EUR 28 million (property assets valued at
  EUR 19 million, fund portfolio at EUR 12 million).

**Verify all figures with the owner's current data before sending to
buyers.** Room counts differ between the flagship hotel and the whole
complex, and the 2023 transaction is quoted from press reports. Set
`contact` in `hotel_facts.json` to your name, phone and email; while it is
empty the videos show "Serious enquiries only | Price on application".

Source URLs are listed under `sources` in `hotel_facts.json`.
