# Changelog

## 0.8.27 — Show All Influences skip empty meshes

- Show All Influences no longer turns on by default when the mesh has
  no skin influences (the overlay would hide the mesh with nothing to
  draw).

## 0.8.26 — Maya-style relative smooth

- Smooth keeps relative weight transitions between neighboring vertices
  instead of mixing each vertex by its own falloff percentage. Close
  neighbors inherit similar strength, closer vertices weigh more in the
  average, and a strong mix can no longer leave an adjacent vertex at a
  much weaker amount (which caused stretching).

## 0.8.25 — Categorized N-panel

- Sidebar grouped into **Brush**, **Influences**, **All Bones**, and
  **Display** so each block is easy to find. Operators are unchanged.

## 0.8.24 — Narrower Flood button

- Flood takes less width next to Interactive Mirror Paint.

## 0.8.23 — Interactive Mirror Paint

- Renamed the X-Mirror toggle to **Interactive Mirror Paint**.

## 0.8.15 — Add Selected binds armature

- Add Selected stays enabled when a bone is chosen in All Bones.
- Bones that already have a vertex group are skipped.
- If the mesh has no Armature modifier, one is added and linked to
  the selected bones' armature.

## 0.8.14 — Add Selected from All Bones

- Add Selected stays enabled when a bone is chosen in All Bones.
- Bones that already have a vertex group are skipped.

## 0.8.13 — All Bones deform filter

- All Bones now hides bones whose Deform option is off.

## 0.8.12 — All Bones list

- Clicking a bone name in All Bones no longer selects it.
- All Bones lists only bones with Deform enabled.

## 0.8.11 — Add Selected influences

- New **Add Selected** button above Live Select: creates vertex groups
  on the mesh for the selected pose bones.

## 0.8.10 — Influence list search

- Removed the extra search field above Live Select.
- The influence list's own search (magnifying glass at the bottom of
  the list) now filters bones by name.

## 0.8.9 — All Bones rollout

- New **All Bones** rollout under the influence list: every bone in the
  scene, with a name filter that keeps focus while typing.

## 0.8.8 — Hold-S / hold-D session fix

- The picker session now derives its behavior from the physical key
  that started it: **S is always Add, D is always Subtract**, and the
  matching key's release always ends the session. Previously the mode
  could come from a stale keymap property, so a hold-S ran as Subtract
  (hovering deselected nothing, and releasing S never exited).
- Added after a D pass: holding S selects hovered bones again as
  expected.

## 0.8.7 — Hold-D release fixes

- Releasing D (and Esc/RMB cancels) now forces an immediate viewport
  redraw: the pick overlay / bone x-ray highlight is cleared at once
  instead of staying visually stuck until the next redraw.
- Removed dead leftover code in the pick commit path (it referenced
  undefined display variables).

## 0.8.6 — Bind Nearest row layout

- The Bind Nearest row is rearranged: **Bind Nearest**, **Remove
  Selected** (text button), then the Selected (bone icon) and Mirror
  (mirror icon) options as compact icon-only toggles at the end.

## 0.8.5 — Show All Influences on by default

- **Show All Influences is now on by default**: opening a .blend seeds
  the multi-color display on (previously 0.5.7 forced it off on every
  file open). The stale display stash from the previous file is still
  cleared first. In Object Mode — where the overlay would hide the
  mesh — the on-choice is stashed and automatically re-applied the
  moment Weight Paint is entered, no matter how the mode is entered.
- Turning it off stays a normal user choice and is remembered as usual.

## 0.8.4 — Remove Selected bones from the skin

- New **X** button next to Bind Nearest: removes the selected pose
  bones from the skin. Their weights are stripped from the vertices
  **without redistribution** — other bones keep their weights, so a
  vertex's total may drop below 1 — and the removed vertex groups are
  deleted. Respects the paint mask; undo-able with Ctrl+Z (weight undo
  restores stripped weights; Blender undo restores the group deletion).

## 0.8.3 — Horizontal F drag

- F / Shift+F now follow pure horizontal mouse movement: dragging
  right always increases the radius / strength, dragging left always
  decreases, starting from the value at key press. Vertical movement is
  ignored during the adjust.

## 0.8.2 — F resize starts from the current value

- Fix: F / Shift+F now add the drag offset to the value the key was
  pressed with (Blender's native radial control), so the ring starts at
  its current radius/strength instead of collapsing to zero until the
  cursor passes the anchor distance.

## 0.8.1 — F adjust survives the key release

- Clarification + hardening of the native-style resize: the F flow is
  already press-and-release (no holding) — press F, let go, move the
  mouse to size the ring, left click sets it, right click / Esc
  cancels. The F key release is now consumed while adjusting so no
  stray event can end the resize early.

## 0.8.0 — Hold-Shift temporary brush + native F resize

- **Hold Shift** in Weight Paint (while the brush session is not
  running) to temporarily activate the DV Skin tool: Shift+drag paints
  with the smooth brush, releasing Shift restores the previous brush
  and closes any session started during the hold. Shift pressed over
  the sidebar/UI is ignored.
- **F resize rewritten to match Blender's native brush resize**: press
  F once, the ring anchors under the cursor, dragging directly sets the
  radius (screen distance mapped to world units at the anchor's depth),
  **left click sets the size** and cannot accidentally paint; right
  click or Esc cancels (previous radius restored). The OS cursor is no
  longer warped/pinned. Shift+F strength adjust uses the same flow,
  full strength at ~200 px of drag.

## 0.7.7 — Assign Shortcut actually appears now

- The toggle/start operators are re-registered under the `paint.`
  prefix (`paint.skin_toggle_x_mirror`, `paint.skin_toggle_xray_all`,
  `paint.skin_toggle_show_influences`, `paint.skin_start_tool`).
  Blender's right-click **Assign Shortcut...** entry only shows when
  `WM_keymap_guess_opname` resolves a keymap, and that resolver matches
  operator idnames by prefix — custom `skin_tools.*` ids matched
  nothing (only Add to Quick Favorites appeared). The `paint.` prefix
  routes assigned shortcuts into the current mode's keymap.
- Panel buttons updated to the new ids; behavior unchanged.

## 0.7.6 — Shortcut-assignable toggles, no extra buttons

- The panel keeps its original layout — no new command section. The
  X-Mirror, X-Ray All Bones and Show All Influences toggles are now
  drawn as operator buttons styled like checkboxes (checkmark + pressed
  state follow the setting), so right-clicking them offers **Assign
  Shortcut** and **Add to Quick Favorites**. Plain property widgets
  never get those entries; that menu is hard-coded by button type in
  Blender, so this is the only way to make a toggle shortcut-assignable.
- Start Tool (Weight Paint + brush activation) stays available as the
  `skin_tools.start_tool` operator for search/keymap/Quick Favorites.

## 0.7.5 — Shortcut-assignable commands

- New **Shortcut Commands** section in the sidebar with four operator
  buttons that support Blender's right-click **Assign Shortcut** and
  **Add to Quick Favorites** (property checkboxes cannot get these):
  - **Start DV Skin** — enters Weight Paint and activates the brush,
    from any mode, from a shortcut or Quick Favorites.
  - **Toggle Show All Influences** — multi-color display on/off.
  - **Toggle X-Ray All Bones** — bone x-ray display on/off.
  - **Toggle X Mirror** — brush mirror painting on/off.
- Explanation: right-click Assign Shortcut / Add to Quick Favorites
  exist only for operator buttons; property widgets (sliders, toggles,
  enum rows) never get those entries — this is core Blender behavior,
  not an addon limitation.

## 0.7.4 — Brush mode buttons in two rows

- The sidebar's brush mode buttons are arranged in two rows of three
  (Smooth / Sharpen / Stitch and Replace / Add / Remove) instead of one
  crowded row. Behavior and selection highlighting are unchanged.

## 0.7.3 — Brush modes remember their intensity

- Switching brush modes (Smooth / Sharpen / Stitch / Replace / Add /
  Remove) no longer resets the intensity to the factory default every
  time. Each mode now remembers the last value the user set: leaving a
  mode stashes its intensity, returning to it restores it. Factory
  defaults apply only the first time a mode is entered per session.

## 0.7.2 — Stitch edge fallback for mismatched seams

- Stitch and Sync Border Weights now handle **mismatched tessellation**:
  when a border vertex has no vertex partner within the Stitch
  Threshold, it is projected onto the nearest border edge of a
  *different* border loop (own loops and neighbor-touching edges are
  excluded) and its partner weights are interpolated along that edge at
  the projection point. Vertex partners still win when they exist.
- The edge projection never writes the edge endpoints — only the
  projected vertex moves, gradually converging onto the edge weights
  over continued strokes / iterations.

## 0.7.1 — Sync Border Weights while smoothing

- New **Sync Border Weights** option (Smooth / Sharpen): after every
  stamp, each border vertex with a partner across a split seam (within
  the new **Stitch Threshold**) is averaged with that partner, so both
  open border edges keep matching weights and cannot pull apart while
  brushing. Partners outside the gathered set are included and written.
- New **Stitch Threshold** setting (local mesh units, like Mirror
  Threshold; 0 = half average edge length) shared by Stitch and the
  sync pass — the stitch partner map rebuilds in place when it changes.
- Undo/redo covers the synced partner vertices (brush strokes and
  Flood alike), so Ctrl+Z never leaves one side of a seam reverted
  while the other stays synced.

## 0.7.0 — Stitch brush + Skip Border Edges

- New **Stitch** brush mode: blends border vertices toward their
  nearest partner across open seam gaps (both sides converge to the
  midpoint), so split shells get matching weights along the border.
  Partners are precomputed from the rest pose; unpaired vertices are
  left untouched. Iterations work, and Flood applies the stitch to the
  whole mesh / paint mask.
- New **Skip Border Edges** option (Smooth / Sharpen): vertices on
  open boundary edges are excluded from gathering, so normal smoothing
  can never pull a split seam out of alignment.
- Stitch appears in the mode list and HUD, has its own cursor color
  (violet), and its flood warns when no stitchable pairs exist.

## 0.6.1 — Release packaging (no code changes vs 0.6.0)

## 0.6.0 — Custom mirror naming pattern

- New **Mirror Pattern** field (Advanced section): type one example bone
  showing your side convention (`R-arm`, `Arm_R`, `R__arm`, `RIGHT_arm`).
  The addon detects the rule (prefix/suffix + separator, or Right/Left
  words) and shows it as a hint below the field. X-Mirror painting,
  Mirror Weights and Bind Nearest (Mirror) try this rule first, then fall
  back to the built-in `.L`/`.R` rules. Empty or unrecognized input keeps
  the old behavior exactly.

## 0.5.9 — Interactive X-Mirror paints the mirrored bone

- Brush **X Mirror** for Replace / Add / Remove now paints the
  opposite-side influence on mirrored vertices (paint `R.arm`, the other
  side receives `L.arm`). Center bones paint the same bone both sides;
  a missing opposite group skips the mirrored vertex instead of
  assigning the wrong bone. `SELECTED` target isolation follows the
  bone (selecting `R.arm` lets `L.arm` paint on the mirrored side).
- Smooth / Sharpen with X Mirror unchanged (symmetric multi-influence op).

## 0.5.8 — Maya-style multi-source Copy Skin Weights

- **Use Selected as Sources** toggle in the Transfer Skin Weights
  panel: the active mesh is the target and every other selected mesh is
  a source (Maya workflow — select shirt + pants + belt, apply on the
  belt). The single "Source Object" picker still works when off.
- Per-vertex source assignment: every target vertex samples **every**
  source surface and inherits from the nearest one, so a target
  spanning several overlapping garments truly follows each of them in
  the intersection areas.
- Core rewrite: `copy_skin_weights_multi()` samples all sources once,
  picks the nearest surface per vertex by sampled distance, and maps
  influences per source; the old single-source entry point is a
  back-compat wrapper.
- The panel shows the live source count and the target name while the
  multi-source mode is on. Paint mask, locked groups, association
  modes and normalize all still apply.

## 0.5.7 — Show All Influences forced off on file open

- Opening a `.blend` now always starts with **Show All Influences off**:
  the `load_post` handler (`_reset_show_all_after_load`) clears the
  toggle, restores the native heatmap/mesh visibility, and drops any
  stale display stash from the previous file. Deferred via timer like
  the Object-Mode auto-exit (direct in background mode).
- The default-on behavior is unchanged for the other paths: enabling
  the addon mid-session still starts the display on; tool
  disable/enable keeps remembering the user's toggle. Only a file open
  resets it.
- `_boot_ui` re-applies its hide only when the toggle is actually on,
  so it cannot resurrect the overlay after the load reset.

## 0.5.6 — Export / Import per-vertex skin weights; panel renamed

- **Transfer Skin Weights** — the "Copy Skin Weights" sub-panel is
  renamed and now hosts a new per-vertex file section alongside the
  mesh-to-mesh copy.
- **Export Skin Weights** (`skin_tools.export_skin_weights`): writes
  the whole mesh's per-vertex weights to JSON — `groups` by name, one
  `[group_index, weight]` list per vertex index. Paint mask is ignored
  (a data export must stay complete). Usable as a backup or to
  transfer onto a mesh with matching vertex order.
- **Import Skin Weights** (`skin_tools.import_skin_weights`): reads the
  file back onto the active mesh — groups matched by name (missing
  ones created), locked groups protected, weights written per vertex
  index via the batch writer, imported groups fully replaced per
  vertex (groups absent from the file are untouched). Reports a
  warning when the vertex count differs from the file.
- New modules: `core/weights_io.py` (format + batch I/O),
  `ops/weights_io.py` (file-selector operators).
- JSON format (version 1) documented in `core/weights_io.py`.

## 0.5.5 — Fix: Show All Influences / Wireframe now truly remembered

0.5.4 stashed the display toggles in `shutdown_tool` and restored them
on `invoke`, but re-enabling the tool from the toolbar does not invoke
anything until a click, so the values still appeared forgotten.

- `shutdown_tool` **no longer touches** Show All Influences / Wireframe
  at all. The overlay draw handler lives for the whole addon session,
  so the colored display simply persists after the brush exits —
  nothing to remember, nothing to restore. Only a genuine
  toggle-off by the user (via the update callback) clears the
  native-heatmap stash.
- The stash/restore pair remains solely for the Object-Mode
  auto-exit, which legitimately must clear the toggle (the mesh would
  stay hidden otherwise) and re-applies the user's values when
  returning to Weight Paint (`restore_display_state` in
  `enter_weight_paint` and brush `invoke`).
- `_boot_ui` applies the default-on Show All Influences at addon
  startup (the RNA default never fires the update callback, so the
  native heatmap would otherwise stay visible on the first session).
- `remember_display_state` is now first-wins so repeated shutdowns
  cannot overwrite the stashed choice with cleared values.

## 0.5.4 — Defaults & display-state memory; orient-ring removed

- **Removed** the automatic surface-oriented brush ring (`_draw3d`,
  `_hit_normal`, its draw handler and all bookkeeping). The flat
  screen-space ring is the single cursor again.
- **Per-mode default Intensity** via a mode-switch update: Replace and
  Remove default to **1.0**; Smooth, Sharpen and Add default to **0.1**.
  A value the user sets manually always wins afterwards (the default
  applies only on the switch itself).
- **Show All Influences and Wireframe are remembered**: both now default
  **on**, and the values survive a brush stop / tool disable-re-enable
  / Object-Mode auto-exit (stashed in `shutdown_tool` and the
  depsgraph auto-exit, restored on tool invoke and on entering Weight
  Paint). Previously `shutdown_tool` force-cleared
  `show_all_influences`, so the user's toggle never survived a session.
- **Front Faces Only now defaults off.**

## 0.5.3 — Invert influence-list selection

- New `skin_tools.bones_select_invert` operator (`ops/pick_influence.py`):
  flips the pose-bone selection of every deform bone of the active mesh's
  armature — exactly the rows the N-panel influence list shows.
- New checkbox button in the N-panel influence-list header row
  (`ui/panel.py`), between "Live Select" and the X (deselect all) button.
  Useful for flipping a large multi-selection before Bind Nearest
  (Selected) or the brush's Selected-Bones target.
- Registered in `ops/__init__.py`.

## 0.5.2 — Stale-geometry auto-repair (fixes "brush stops working until tool restart")

### Root cause of the disable/re-enable bug

`build_mesh_cache()` ran **only once**, in `SKIN_OT_smooth_paint.invoke()`,
and snapshotted the *evaluated* (posed, deformed) surface:

- `world_co` / `world_no` — world-space vertex positions + normals
- `kdtree` — spatial index over those positions
- `bvh` — `BVHTree.FromObject()` of the evaluated surface (all raycasting)
- `matrix_world` / `matrix_world_inv`, `avg_edge`, `paint_mask`

During use, weight writes (`refresh_overlay` → `mesh.update()` +
`update_tag()`), stroke undo, pose tweaks and object moves make the
depsgraph re-evaluate the armature modifier, so the **visible surface
moves** while the brush kept raycasting and gathering against the
enable-time snapshot. Consequences matched all reported symptoms:

- stale kdtree distances → falloff factors ≈ 0 → "brushing does nothing"
- stale BVH → ray hits the old surface → gathers land elsewhere →
  irregular/inconsistent smoothing
- steep camera angles amplify the parallax between old and new surface →
  "more noticeable at grazing angles" (a symptom, not the cause)

`modal()` only guarded `obj.name` / `obj.mode`, so nothing ever rebuilt
the geometry. Disabling/re-enabling the tool destroyed the operator
instance → fresh `build_mesh_cache()` → instantly fixed. That reset was
the entire fix.

### Fixes in 0.5.2

- **`core/mesh_data.py`**
  - depsgraph epoch watch (`_on_depsgraph_update` handler +
    `geom_epoch()`): any depsgraph update bumps a global counter that
    live caches compare against (cheap flag check per event).
  - `MeshCache.position_drift()`: full-array max world-space movement of
    the current evaluated mesh vs the cache (also folds in the object
    transform). Returns `inf` when the vertex count changed (topology
    edit) — a signal the cache is unusable, not just stale.
  - `MeshCache.refresh_geometry(rebuild_spatial=True)`: in-place repair
    that preserves topology, weights and all stroke bookkeeping. Cheap
    tier always refreshes world coords/normals/matrix/paint mask/edge
    lengths; `rebuild_spatial` adds KDTree + BVH rebuild.
  - `MeshCache.edge_verts` stored at build time so `avg_edge` can be
    refreshed without re-reading topology.
  - `register_geom_watch()` / `unregister_geom_watch()` lifecycle.
- **`ops/smooth_brush.py`**
  - `_ensure_fresh_geometry()` called in `modal()` before any
    raycast/gather, and with `force=True` in `_begin_stroke()` (full
    spatial rebuild at every stroke start — the exact moment the old
    disable/re-enable cycle rebuilt everything).
  - Tiered repair: drift ≤ 1e-4 → no-op; small drift → cheap refresh;
    drift > max(0.08 × avg_edge, 0.1 × radius) or stroke start → also
    rebuild KDTree/BVH; vertex-count change → full cache rebuild.
  - SURFACE gather now **recomputes distances from the current
    `world_co` snapshot** and re-filters by radius after KDTree
    candidate selection, so falloff can never run on stale distances
    even between spatial rebuilds.
  - `DVSKIN_DEBUG_GATHER=1` env var logs drift checks, refreshes and
    rebuilds.

### Result

The tool now detects drifted geometry itself and repairs it at the
correct lifecycle point (per-event fast path, full spatial rebuild at
stroke start). The manual disable/re-enable workaround is no longer
needed.
