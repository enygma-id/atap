# SPDX-License-Identifier: AGPL-3.0-only
"""
End-to-end browser test of playground/index.html against mock_server.py
(or against a running `atap serve` via --url).

    python e2e_playground.py --data DIR/stepped [--url http://127.0.0.1:8765/] [--chromium PATH]

Needs: pip install playwright && python -m playwright install chromium.
Covers: preflight (ID + UTM), run, stats/skipped/header, part + building
tooltips and hierarchy tree, acceptance Tests C, F and G, engine failure surfaced in UI,
queue position for a second user, cancel while queued / uploading /
running, local file open, legacy-file rejection, tampered-file detection.
Basemap tile errors are ignored (they depend on network access).
"""
import argparse
import asyncio
import json
import os
import re
import subprocess
import sys
import tempfile
import time

from playwright.async_api import async_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
CHIP = "document.getElementById('chip').textContent"


def check(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond:
        check.failed += 1
check.failed = 0


async def page_with_inputs(browser, url, data, footprint="footprints_fid.geojson"):
    pg = await browser.new_page()
    pg.errs = []
    pg.on("pageerror", lambda e: pg.errs.append(str(e)))
    def on_console(m):
        if m.type != "error":
            return
        src = f"{m.text} {(m.location or {}).get('url', '')}"
        if "big.go.id" in src or "favicon" in src:
            return                      # basemap availability depends on the network
        pg.errs.append(src.strip())
    pg.on("console", on_console)
    await pg.goto(url); await pg.wait_for_timeout(800)
    await pg.set_input_files("#file-footprint", os.path.join(data, footprint))
    await pg.set_input_files("#file-dsm", os.path.join(data, "dsm.tif"))
    await pg.set_input_files("#file-dtm", os.path.join(data, "dtm.tif"))
    await pg.wait_for_timeout(400)
    return pg


async def run(url, data, chromium, offline=False):
    async with async_playwright() as p:
        kw = {"args": ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"]}
        if chromium:
            kw["executable_path"] = chromium
        b = await p.chromium.launch(**kw)
        context = await b.new_context(viewport={"width": 1400, "height": 900})
        if offline:
            await context.route("https://**/*", lambda route: route.abort())

        # --- preflight + main run -------------------------------------------------
        A = await page_with_inputs(context, url, data, "footprints.geojson")
        check(await A.input_value("#p-id_field") == "id", "properties.id automatically selected")
        check(not await A.is_disabled("#btn-run"), "run enabled with automatic properties.id")
        await A.evaluate("""() => {
          state.footprintInfo.props = state.footprintInfo.props.map(p => ({building_code:p.id}));
          state.footprintInfo.fieldCache = {};
          state.footprintInfo.keys = ['building_code'];
          refreshIdOptions(state.footprintInfo.keys);
          renderFootprintInfo(); refreshRunButton();
        }""")
        check(await A.is_disabled("#btn-run"), "run blocked without selected properties key")
        await A.select_option("#p-id_field", "building_code"); await A.wait_for_timeout(200)
        check(not await A.is_disabled("#btn-run"), "alternative properties key selected from dropdown")
        await A.close()
        A = await page_with_inputs(context, url, data, "footprints.geojson")
        buttons = A.locator('#p-keep_properties-buttons button')
        keys = await A.evaluate("state.footprintInfo.keys")
        check(await buttons.count() == len(keys) and
              await A.locator('#p-keep_properties-buttons button[aria-pressed="true"]').count() == len(keys),
              "all footprint properties start active as attribute buttons")
        await A.locator('#p-keep_properties-buttons button').first.click()
        copied = await A.evaluate("collectParams().keep_properties")
        check(len(copied) == len(keys) - 1, "attribute toggle excludes one property from request")
        await A.locator('#p-keep_properties-buttons button').first.click()
        for index in range(await buttons.count()):
            await buttons.nth(index).click()
        check(await A.evaluate("collectParams().keep_properties.length") == 0,
              "all attribute toggles off sends an explicit empty array")
        await A.evaluate("setParam('keep_properties', ['label,code'])")
        check(await A.evaluate("collectParams().keep_properties") == ['label,code'],
              "property keys containing commas stay intact")
        await A.evaluate("resetParams()")
        check(await A.input_value('#p-id_field') == 'id' and
              await A.evaluate("collectParams().keep_properties") == keys,
              "reset restores automatic ID and all footprint attributes")
        for key, value in [('base_elevation_stat', 'median'), ('ground_source_type', 'DEM')]:
            await A.locator(f'#p-{key}-buttons button[data-value="{value}"]').click()
            check(await A.evaluate(f"collectParams().{key}") == value and
                  await A.locator(f'#p-{key}-buttons button[aria-pressed="true"]').count() == 1,
                  f"{key} button group selects exactly one value")
        await A.locator('#p-base_elevation_stat-buttons button[data-value="min"]').click()
        await A.locator('#p-ground_source_type-buttons button[data-value="DTM"]').click()
        check("matches the data area" in await A.inner_text("#footprint-info"), "UTM zone check")
        await A.click("#btn-run")
        await A.wait_for_function(f"{CHIP}.includes('TERRAIN') || {CHIP}.includes('FAILED')", timeout=180000)
        check("TERRAIN" in await A.inner_text("#chip"), "run completes")
        stats = await A.inner_text("#stats")
        check("4\nbuildings" in stats and "8\nparts" in stats, f"stats 4 buildings / 8 parts ({stats.split()[:4]})")
        check("B5_out" in await A.inner_text("#skipped-section"), "skipped building listed")

        # --- spec Test C / Test G --------------------------------------------------
        r = await A.evaluate("""() => {
          const before = JSON.stringify(state.data), out = {};
          for (const g of [false, true]) {
            state.groundElevation = g; state.renderCache = null;
            const f = renderData().features.find(f => f.properties.parent_part_id != null);
            out[g] = {z: f.geometry.coordinates[0][0][2], h: f.properties.part_height_m,
                      agl: f.properties.base_height_agl_m, elev: f.properties.base_elevation_m};
          }
          state.groundElevation = false; state.explode = true; state.renderCache = null; renderData();
          out.unchanged = before === JSON.stringify(state.data);
          state.explode = false; state.renderCache = null; updateLayers();
          return out; }""")
        check(r["false"]["z"] == r["false"]["agl"] and r["true"]["z"] == r["true"]["elev"]
              and r["false"]["h"] == r["true"]["h"], "Test C: ground toggle translates only")
        check(r["unchanged"], "Test G: canonical data unchanged by explode/toggle")

        # --- hover tooltip -----------------------------------------------------------
        await A.wait_for_timeout(1500)   # let the fit-to-data camera transition finish
        pt = await A.evaluate("""() => {
          const f = state.data.features.reduce((a,b) => b.properties.top_height_agl_m > a.properties.top_height_agl_m ? b : a);
          const ring = f.geometry.coordinates[0]; let x = 0, y = 0; ring.slice(0,-1).forEach(c => {x += c[0]; y += c[1];});
          const n = ring.length - 1;
          return deckgl.getViewports()[0].project([x/n, y/n, f.properties.top_height_agl_m]); }""")
        await A.mouse.move(pt[0], pt[1]); await A.wait_for_timeout(600)
        check("Raster evidence".upper() in (await A.inner_text("#tooltip")).upper(), "part tooltip on hover")

        # --- hierarchy tree / spec Test F -------------------------------------------
        tree_before = await A.evaluate("JSON.stringify(state.data)")
        await A.click("#mode-building")
        grouping = await A.evaluate("""() => [...state.byObject].every(([oid, parts]) =>
          parts.length > 0 && parts.every(f => f.properties.object_id === oid) &&
          parts.every(f => f.properties.parent_part_id == null ||
            parts.some(parent => parent.properties.part_id === f.properties.parent_part_id)))""")
        check(grouping, "Test F: parts group by object_id and parents stay within the building")
        pinned = await A.evaluate("""() => {
          const feature = state.byObject.get('B2')[0];
          const layer = deckgl.props.layers.find(layer => layer.id === 'atap-parts');
          layer.props.onClick({object: feature});
          return state.pinnedObjectId;
        }""")
        await A.wait_for_selector("#hierarchy-tree")
        rows = A.locator("#hierarchy-tree [data-tree-part]")
        check(pinned == "B2" and await rows.count() == 2, "building click pins its complete hierarchy")
        text = await A.inner_text("#hierarchy-tree")
        check("Level 0" in text and "Level 1" in text and "m³" in text,
              "tree shows level, AGL interval and volume")
        first = rows.first
        await first.hover()
        check(await A.evaluate("Boolean(state.treeHoveredPartId)"), "tree hover highlights one part")
        await first.focus()
        check(await A.evaluate("document.activeElement.hasAttribute('data-tree-part')"),
              "tree nodes accept keyboard focus")
        root = A.locator("#hierarchy-tree details").first
        await root.locator(":scope > summary").click()
        check(not await root.evaluate("node => node.open"), "hierarchy nodes collapse")
        check(tree_before == await A.evaluate("JSON.stringify(state.data)"),
              "Test G: tree interactions leave canonical data unchanged")
        min_font = await A.evaluate("""() => Math.min(...[...document.querySelectorAll('.panel *')]
          .filter(el => el.textContent.trim() && getComputedStyle(el).display !== 'none')
          .map(el => parseFloat(getComputedStyle(el).fontSize)).filter(Number.isFinite))""")
        check(min_font >= 10, f"visible panel text is at least 10 px ({min_font}px)")

        # --- reuse transport, file changes, expiry, and download names ------------------
        await A.click("#tab-btn-run")
        submitted = []
        def record_submit(request):
            if request.method == "POST" and request.url.endswith("/api/jobs"):
                body = request.post_data_buffer or b""
                # Chromium postData omits uploaded Blob fields; the server's
                # mutually exclusive input contract identifies upload requests.
                reuse = b'name="source_job_id"' in body
                submitted.append({"reuse": reuse, "files": not reuse, "size": len(body)})
        A.on("request", record_submit)
        canonical = """() => {
          const d = JSON.parse(JSON.stringify(state.data));
          delete d.process; delete d.processing.execution; return JSON.stringify(d);
        }"""
        original = await A.evaluate(canonical)
        async def rerun():
            previous = await A.evaluate("state.activeRun")
            await A.click("#btn-run")
            await A.wait_for_function("previous => state.activeRun !== previous && !state.job", arg=previous,
                                     timeout=60000)
        await A.evaluate("setParam('workers', 2)")
        await rerun()
        check(submitted[-1]["reuse"] and not submitted[-1]["files"] and submitted[-1]["size"] < 5000,
              "parameter rerun sends only source reference and parameters")
        check(original == await A.evaluate(canonical), "reused input gives equivalent output with workers 2")
        job_id = await A.evaluate("state.activeRun")
        response = await A.request.get(f"{url.rstrip('/')}/api/jobs/{job_id}/artifacts/output")
        check(bool(re.search(r'atap_\d{8}T\d{6}Z_' + job_id[:8] + r'\.geojson',
                             response.headers.get("content-disposition", ""))), "output download has UTC timestamp and job ID")
        await A.set_input_files("#file-dsm", [])
        await A.set_input_files("#file-dsm", os.path.join(data, "dsm.tif"))
        await rerun()
        check(submitted[-1]["files"] and not submitted[-1]["reuse"], "changing a selected file uploads new input")
        await A.evaluate("state.reusableInputs.jobId = '00000000-0000-0000-0000-000000000001'")
        previous_count = len(submitted)
        previous_errors = len(A.errs)
        await rerun()
        check(len(submitted) == previous_count + 2 and submitted[-2]["reuse"] and submitted[-1]["files"],
              "expired input reference automatically falls back to upload")
        # Only this deliberate missing-source response is expected to log 404.
        A.errs = [err for index, err in enumerate(A.errs)
                  if index < previous_errors or not (
                      "404 (Not Found)" in err and err.endswith("/api/jobs"))]


        # --- engine failure surfaced ---------------------------------------------------
        await A.click("#tab-btn-run"); await A.fill("#p-working_crs", "EPSG:4326")
        await A.click("#btn-run")
        await A.wait_for_function(f"{CHIP}.includes('FAILED')", timeout=60000)
        await A.wait_for_timeout(1200)
        check("working_crs" in await A.inner_text("#status"), "engine error stays visible in status")
        await A.click("#btn-use-utm")

        # --- queue + cancel ----------------------------------------------------------------
        queue_data = os.path.join(os.path.dirname(data), "bench")
        if not os.path.isdir(queue_data):
            queue_data = data
        B = await page_with_inputs(context, url, queue_data)
        C = await page_with_inputs(context, url, queue_data)
        await B.evaluate("state.params.workers = 1; document.getElementById('p-workers').value = 1")
        await C.evaluate("state.params.workers = 1; document.getElementById('p-workers').value = 1")
        await B.click("#btn-run")
        check(await B.inner_text("#btn-run-label") == "Cancel upload", "button guards against double submit during upload")
        await B.wait_for_function(f"!{CHIP}.includes('UPLOADING')", timeout=60000)
        await C.click("#btn-run")
        await C.wait_for_function(f"{CHIP}.includes('QUEUED')", timeout=60000)
        check("QUEUED" in await C.inner_text("#chip"), "second user sees queue position")
        await C.click("#btn-run")
        await C.wait_for_function(f"{CHIP}.includes('CANCELLED')", timeout=30000)
        check(True, "cancel while queued")
        await B.click("#btn-run")   # cancel B while running
        await B.wait_for_function(f"{CHIP}.includes('RUN CANCELLED')", timeout=60000)
        check("No output" in await B.inner_text("#status"), "cancel while running, nothing written")

        # --- local files -----------------------------------------------------------------------
        tmp = tempfile.mkdtemp()
        json.dump({"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {"building_height_m": 5}, "geometry": None}]},
                  open(os.path.join(tmp, "legacy.geojson"), "w"))
        await A.set_input_files("#file-result", os.path.join(tmp, "legacy.geojson")); await A.wait_for_timeout(400)
        check("legacy" in (await A.inner_text("#status")).lower(), "legacy LOD1 file rejected")
        good = await A.evaluate("JSON.stringify(state.data)")
        d = json.loads(good); d["features"][-1]["properties"]["part_height_m"] += 1
        json.dump(d, open(os.path.join(tmp, "tampered.geojson"), "w"))
        await A.set_input_files("#file-result", os.path.join(tmp, "tampered.geojson")); await A.wait_for_timeout(500)
        check("INVARIANT" in await A.inner_text("#chip"), "tampered file flagged by invariant checks")

        errs = A.errs + B.errs + C.errs
        check(not errs, f"no page errors ({errs[:3]})")
        await context.close(); await b.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True, help="stepped dataset dir from make_synthetic.py")
    ap.add_argument("--url", help="use a running server instead of starting mock_server.py")
    ap.add_argument("--chromium", help="custom chromium executable")
    ap.add_argument("--offline", action="store_true", help="block external requests")
    a = ap.parse_args()
    srv = None
    url = a.url
    if not url:
        srv = subprocess.Popen([sys.executable, os.path.join(HERE, "mock_server.py"), "8765"],
                               env={**os.environ, "MOCK_DELAY": "8"})  # long enough to cancel while queued AND while running
        time.sleep(1.5)
        url = "http://127.0.0.1:8765/"
    try:
        asyncio.run(run(url, os.path.abspath(a.data), a.chromium, a.offline))
    finally:
        if srv:
            srv.terminate()
    print(f"\n{check.failed} failed")
    sys.exit(1 if check.failed else 0)


if __name__ == "__main__":
    main()
