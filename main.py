import requests
import urllib
import json
import re

import tqdm
from subprocess import check_output, DEVNULL
import os
import tempfile

import models
import script as scr
import state

SOX = "/opt/homebrew/bin/sox"
MPLAYER = "/opt/homebrew/bin/mplayer"

### Script reader
def download_mp3(fname, url):
    doc = requests.get(url)
    with open(fname, 'wb') as f:
        f.write(doc.content)

def play(fname):
    check_output([MPLAYER, fname], stderr=DEVNULL)

def read_script(script, file_prefix="post"):
    pbar = tqdm.tqdm(total = len(script))
    for ix, block in enumerate(script):
        if isinstance(block, dict) and "silence" in block:
            continue
        if state.has(block):
            audio_url = models.read_text(block)
            fname = f"{file_prefix}-{str(ix).zfill(5)}.mp3"
            download_mp3(fname, audio_url)
            state.put(bloc, {"url": audio_url, "file": fname})
        pbar.update(1)
    pbar.close()
    return script

def read_complete_p(script):
    for block in script:
        if isinstance(block, str) and not state.has(block):
            return False
    return True

### Sound manipulation
def info(sound_fname):
    res = check_output([SOX, "--i", sound_fname])
    splits = (re.split(" *: +", ln) for ln in res.decode("utf-8").splitlines() if ln)
    return {k.lower().replace(' ', '-'): v for k, v in splits}

def silence(duration, rate=24000, channels=1):
    fname = f"silence-{duration}.mp3"
    if not os.path.isfile(fname):
        check_output([
            SOX, "-n",
            "-r", str(rate), "-c", str(channels), # These must match the downloaded files from `read`, otherwise catting them later is rough
            fname,
            "trim", "0.0",
            str(duration)])
    return fname

def cat(script, output):
    inputs = []
    for block in script:
        if state.has(block):
            inputs.append(state.get(block)['file'])
        elif isinstance(block, dict):
            fname = silence(block['silence'])
            state.put(block, {'file': fname})
            inputs.append(fname)
    check_output([SOX] + inputs + [output])
    return output


### Top-level interface components
def _prefix_from_target(target):
    if target.startswith("http"):
        return urllib.parse.urlparse(target).path.split("/")[-1]
    elif os.path.isfile(target):
        return os.path.splitext(os.path.split(target)[-1])[0]

def read(target, output=None):
    try:
        script = scr.script_from(target)
        if output is None:
            prefix = _prefix_from_target(target)
            output = tempfile.mkstemp(".mp3", prefix=prefix, dir=".")[1]
        else:
            prefix, _ = os.path.splitext(output)
        while not read_complete_p(script):
            read_script(script, file_prefix=prefix)
        state.save(f"{prefix}.json")
        return cat(script, output)
    except Exception as e:
        print(f"Exception: {e}")
        return None

if __name__ == "__main__":
    for target in sys.argv[1:]:
        print(f"Reading {target}...")
        res = read(target)
        if res is None:
            print("  fail")
        else:
            print("  done")
