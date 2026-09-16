# Output schema

ATAP output is an RFC 7946 GeoJSON FeatureCollection using profile `0.6`. The machine-readable schema is [`schema/atap-elevation-0.6.schema.json`](../schema/atap-elevation-0.6.schema.json).

Top-level members are `type`, `name`, `atap`, `process`, `inputs`, `processing`, `vertical_reference`, `summary`, and `features`. Each feature is one mass part. `Feature.id` equals `part_id`; `object_id` groups a building; `parent_part_id` and `part_level` define its tree.

Intrinsic height fields use metres above ground. Elevation fields add DTM placement. `part_height_m = top_height_agl_m - base_height_agl_m` and volume is area times height within rounding tolerance.

See [output metadata](output-metadata.md) and [the method](method.md).
