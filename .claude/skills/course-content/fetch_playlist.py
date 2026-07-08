#!/usr/bin/env python3
"""Fetch a YouTube playlist's videos with status/duration for evaluation.

Usage: fetch_playlist.py PLAYLIST_ID OUT.json
"""
import json
import os
import re
import sys
import urllib.parse
import urllib.request

ENV = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", ".env"))
with open(ENV) as f:
    key = next(l.split("=", 1)[1].strip() for l in f
               if l.startswith("YOUTUBE_API_KEY="))

pl_id, out_path = sys.argv[1], sys.argv[2]


def api(endpoint, **params):
    params["key"] = key
    url = f"https://www.googleapis.com/youtube/v3/{endpoint}?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=30) as resp:
        return json.load(resp)


items, page = [], None
while True:
    kw = {"part": "snippet,status", "playlistId": pl_id, "maxResults": 50}
    if page:
        kw["pageToken"] = page
    data = api("playlistItems", **kw)
    items.extend(data.get("items", []))
    page = data.get("nextPageToken")
    if not page:
        break

vids = [it["snippet"]["resourceId"]["videoId"] for it in items]
details = {}
for i in range(0, len(vids), 50):
    data = api("videos", part="status,contentDetails,snippet,statistics",
               id=",".join(vids[i:i+50]), maxResults=50)
    for v in data.get("items", []):
        details[v["id"]] = v


def iso_dur(s):
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", s or "")
    h, mi, se = (int(x) if x else 0 for x in m.groups())
    return h * 3600 + mi * 60 + se


rows = []
for it in items:
    vid = it["snippet"]["resourceId"]["videoId"]
    d = details.get(vid)
    if d is None:
        rows.append({"pos": it["snippet"]["position"], "video_id": vid,
                     "title": it["snippet"]["title"], "dead": True})
        continue
    rows.append({
        "pos": it["snippet"]["position"],
        "video_id": vid,
        "title": d["snippet"]["title"],
        "channel": d["snippet"]["channelTitle"],
        "published": d["snippet"]["publishedAt"][:10],
        "duration_s": iso_dur(d["contentDetails"].get("duration")),
        "embeddable": d["status"].get("embeddable", True),
        "privacy": d["status"].get("privacyStatus"),
        "views": int(d.get("statistics", {}).get("viewCount", 0)),
        "dead": False,
    })

with open(out_path, "w") as f:
    json.dump(rows, f, ensure_ascii=False, indent=1)

alive = [r for r in rows if not r["dead"]]
total = sum(r["duration_s"] for r in alive)
bad_embed = [r for r in alive if not r["embeddable"]]
print(f"playlist={pl_id}")
print(f"videos={len(rows)} alive={len(alive)} dead={len(rows)-len(alive)} "
      f"not_embeddable={len(bad_embed)}")
if alive:
    print(f"channel={alive[0]['channel']}")
    print(f"dates {min(r['published'] for r in alive)} .. {max(r['published'] for r in alive)}")
    print(f"total_duration={total//3600}h{(total%3600)//60:02d}m avg={total//len(alive)//60}m")
for r in rows:
    flag = " DEAD" if r["dead"] else ("" if r["embeddable"] else " NO-EMBED")
    dur = "" if r["dead"] else f" {r['duration_s']//60}:{r['duration_s']%60:02d}"
    print(f"  {r['pos']+1:3d}. {r['title'][:80]}{dur}{flag}")
