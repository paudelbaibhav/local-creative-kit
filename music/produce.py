"""Generate a full song on the local ACE-Step server.

Run with ACE-Step's Python (any Python 3 works; standard library only):
    ACE-Step-1.5/.venv/Scripts/python.exe produce.py songs/example --caption "..." --duration 210 --bpm 75 \
        [--ref my-songs/draft.mp3] [--ref-strength 0.5] [--key "A minor"] [--seed 123]

Reads <song dir>/lyrics.txt, writes <song dir>/<song>-v1.mp3, -v2.mp3 ... and settings.json.

The music server is restarted before each job (fresh = faster, and a reused server
has segfaulted on long songs) and restarted + retried once if it crashes mid-job.

--ref uses a track as a style reference (keeps its sound). The server only accepts
audio files from the system temp folder, so the reference is copied there first.
"""
import argparse
import json
import shutil
import subprocess
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path

API = "http://127.0.0.1:8001"
ACE_DIR = Path(__file__).parent / "ACE-Step-1.5"
SERVER_LOG = Path(__file__).parent / "logs" / "api.log"


def server_up():
    try:
        with urllib.request.urlopen(API + "/health", timeout=3):
            return True
    except Exception:
        return False


def stop_server():
    subprocess.run(["taskkill", "/F", "/T", "/IM", "acestep-api.exe"], capture_output=True)
    for _ in range(15):
        if not server_up():
            return
        time.sleep(1)


def start_server():
    """Launch the ACE-Step API detached, so it outlives this script.

    The server tends to segfault while offloading the DiT after a long job
    (seen on the 2nd+ 210s song on the 6GB card); a fresh process always worked.
    """
    SERVER_LOG.parent.mkdir(exist_ok=True)
    log = SERVER_LOG.open("a", encoding="utf-8")
    flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    subprocess.Popen(
        [str(ACE_DIR / ".venv" / "Scripts" / "acestep-api.exe")],
        cwd=ACE_DIR, stdout=log, stderr=log, creationflags=flags,
        env={**__import__("os").environ, "PYTHONUNBUFFERED": "1"},
    )
    for _ in range(90):
        time.sleep(2)
        if server_up():
            print("Music server started", flush=True)
            return
    raise SystemExit(f"Music server did not start; see {SERVER_LOG}")


def post(path, payload):
    req = urllib.request.Request(
        API + path, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise SystemExit(f"Server rejected {path}: {e.code} {e.read().decode(errors='replace')}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("song_dir", type=Path)
    ap.add_argument("--caption", required=True)
    ap.add_argument("--duration", type=float, required=True)
    ap.add_argument("--bpm", type=int)
    ap.add_argument("--key")
    ap.add_argument("--timesig", help='e.g. "6/8" (dadra feel) or "4/4"')
    ap.add_argument("--ref", type=Path, help="style reference track")
    ap.add_argument("--ref-strength", type=float, help="0-1, how closely to follow the reference")
    ap.add_argument("--seed", type=int)
    ap.add_argument("--language", default="en")
    ap.add_argument("--lyrics", type=Path, help="lyrics file (default: <song dir>/lyrics.txt)")
    ap.add_argument("--tag", default="", help="suffix for output names, e.g. 'ref' -> <song>-ref-v1.mp3")
    ap.add_argument("--src", type=Path,
                    help="cover mode: rebuild this track (keeps its structure/melody) with the given lyrics; "
                         "lyrics '[Instrumental]' re-creates it with no vocals")
    ap.add_argument("--src-strength", type=float, default=1.0, help="cover mode: 1.0 = closest to --src")
    ap.add_argument("--keep-server", action="store_true",
                    help="reuse the running server (default restarts it: a fresh one is ~4x faster on long songs)")
    args = ap.parse_args()

    if not args.keep_server and server_up():
        print("Restarting music server for a clean GPU", flush=True)
        stop_server()

    lyrics = (args.lyrics or args.song_dir / "lyrics.txt").read_text(encoding="utf-8")
    payload = {
        "prompt": args.caption,
        "lyrics": lyrics,
        "task_type": "text2music",
        "audio_duration": args.duration,
        "vocal_language": args.language,
        "audio_format": "mp3",
        "thinking": False,
        "use_format": False,
        "use_cot_caption": False,
        "use_cot_language": False,
        "use_random_seed": args.seed is None,
    }
    if args.bpm:
        payload["bpm"] = args.bpm
    if args.key:
        payload["key_scale"] = args.key
    if args.timesig:
        payload["time_signature"] = args.timesig
    if args.seed is not None:
        payload["seed"] = args.seed
    tmp_dir = Path(tempfile.gettempdir()) / "acestep-src"
    tmp_dir.mkdir(exist_ok=True)
    if args.ref:
        ref_copy = tmp_dir / ("ref-" + args.ref.name.replace(" ", "_"))
        shutil.copy(args.ref, ref_copy)
        payload["reference_audio_path"] = str(ref_copy)
        if args.ref_strength is not None:
            payload["audio_cover_strength"] = args.ref_strength
    if args.src:
        src_copy = tmp_dir / ("src-" + args.src.name.replace(" ", "_"))
        shutil.copy(args.src, src_copy)
        payload["task_type"] = "cover"
        payload["src_audio_path"] = str(src_copy)
        payload["audio_cover_strength"] = args.src_strength

    for attempt in (1, 2):
        if not server_up():
            start_server()
        task_id = post("/release_task", payload)["data"]["task_id"]
        print(f"Job {task_id} started", flush=True)
        start = time.time()
        try:
            while True:
                time.sleep(3)
                item = post("/query_result", {"task_id_list": [task_id]})["data"][0]
                if item["status"] == 1:
                    break
                if item["status"] == 2:
                    raise SystemExit(f"Generation failed: {item.get('result')}")
            break
        except urllib.error.URLError:
            if attempt == 2:
                raise SystemExit("Music server crashed twice on this job; see " + str(SERVER_LOG))
            print("Music server crashed mid-job; restarting and retrying once", flush=True)
    print(f"Done in {time.time() - start:.0f}s", flush=True)

    result = json.loads(item["result"])
    name = args.song_dir.name + (f"-{args.tag}" if args.tag else "")
    for i, r in enumerate(result, 1):
        f = r["file"]  # usually already "/v1/audio?path=<url-encoded>"
        url = API + f if f.startswith("/") else API + "/v1/audio?path=" + urllib.parse.quote(f)
        out = args.song_dir / f"{name}-v{i}.mp3"
        with urllib.request.urlopen(url, timeout=120) as resp, out.open("wb") as f:
            shutil.copyfileobj(resp, f)
        print(f"Saved {out}", flush=True)

    settings = {k: v for k, v in vars(args).items() if v is not None}
    settings = {k: str(v) if isinstance(v, Path) else v for k, v in settings.items()}
    settings["seeds"] = [r.get("seed_value") for r in result]
    settings["task_id"] = task_id
    (args.song_dir / f"settings{'-' + args.tag if args.tag else ''}.json").write_text(json.dumps(settings, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
