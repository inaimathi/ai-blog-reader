import replicate
import requests
import urllib
import json
import re
from bs4 import BeautifulSoup
from PIL import Image
from io import BytesIO
import tqdm
import markdown
import nltk.data
from subprocess import check_output
import os
import tempfile

TOK = nltk.data.load("tokenizers/punkt/english.pickle")
SOX = "sox"

### Cache-related stuff
CACHE = {}

def save_cache(fname):
    with open(fname, 'w') as f:
        f.write(json.dumps(CACHE))

def load_cache(fname):
    global CACHE
    with open(fname, 'r') as f:
        CACHE = json.load(f)
        return CACHE

### Text extraction
def _sanitize(txt):
    return re.sub("’", "'", re.sub("[\[\]]", "", txt.strip()))

def _image_text(url):
    if url in CACHE:
        return CACHE[url]

    img = BytesIO(requests.get(url).content)
    resp = replicate.run(
        "salesforce/blip:2e1dddc8621f72155f24cf2e0adbde548458d3cab9f00c0139eea840d0ac4746",
        input={"image": img}
    )
    caption = re.sub("^Caption: ", "", resp).capitalize()
    CACHE[url] = caption
    return caption

def _element_text(el):
    if el.name == "p":
        return [_sanitize(el.text), {"silence": 0.5}]
    elif el.name == "a":
        return [_sanitize(el.text), "(link in post.)", {"silence": 0.2}]
    elif el.find("img") not in {None, -1}:
        src = json.loads(el.find("img")["data-attrs"])["src"]
        return ["Here we see an image of:", _image_text(src), {"silence": 0.5}]
    elif el.name in {"h1", "h2", "h3"}:
        return [_sanitize(el.text), {"silence": 1.0}]
    elif el.name == "blockquote":
        ps = el.find_all("p")
        if len(ps) == 1:
            return ["Quote:", _sanitize(el.text), {"silence": 0.5}]
        return ["There is a longer quote:"] + [_sanitize(p.text) for p in ps] + [{"silence": 0.5}, "Now we resume the text.", {"silence": 0.5}]
    elif isinstance(el, str):
        if el.strip() == '':
            return []
        else:
            return [el]
    elif el.name in {"ul", "ol"}:
        res = []
        for li in el.find_all("li"):
            res.append(_sanitize(li.text))
            res.append({"silence": 0.5})
        res.append({"silence": 0.5})
        return res
    else:
        print("OTHER", el.name)
        return [el]

def script_from_html(html):
    soup = BeautifulSoup(html, "html.parser")
    return [txt for child in soup.children for txt in _element_text(child)]

def script_from_markdown(md):
    return script_from_html(markdown.markdown(md))

def script_from_substack(post_url):
    parsed = urllib.parse.urlparse(post_url)
    subdomain = parsed.netloc.split(".")[0]
    slug = [p for p in parsed.path.split("/") if p and p != "p"][0]
    url = f"https://{subdomain}.substack.com/api/v1/posts/{slug}"
    resp = requests.get(url).json()
    return [resp["title"], resp["subtitle"]] + script_from_html(resp["body_html"])

def script_from_(thing):
    if thing.startswith("http"):
        if "substack" in thing:
            return script_from_substack(thing)
        else:
            raise Exception(f"Don't know how to get script from '{thing}'")
    elif os.path.isfile(thing):
        with open(thing, 'r') as f:
            if thing.endswith(".md"):
                return script_from_markdown(f.read())
            elif thing.endswith(".html"):
                return script_from_html(f.read())
    else:
        return script_from_html(thing)


### Script normalization
def _break_paragraphs(script):
    for el in script:
        if isinstance(el, str):
            sentences = TOK.tokenize(el)
            if len(sentences) == 1:
                yield el
            else:
                for s in sentences:
                    yield s
                    yield {"silence": 0.1}
        elif isinstance(el, dict):
            yield el

def _merge_silence(script):
    "Merges adjacent silences into longer ones. Also implicitly trims off any trailing silence."
    merged = None
    for el in script:
        if isinstance(el, dict) and "silence" in el:
            if merged is None:
                merged = el
            else:
                merged["silence"] += el["silence"]
        else:
            if merged is None:
                yield el
            else:
                yield merged
                merged = None
                yield el

def normalize_script(script):
    sentences = _break_paragraphs(script)
    merged = _merge_silence(sentences)
    return list(merged)

### Script reader
def download_mp3(fname, url):
    doc = requests.get(url)
    with open(fname, 'wb') as f:
        f.write(doc.content)

def read(text, voice="mol", custom_voice=None):
    model = "afiaka87/tortoise-tts:e9658de4b325863c4fcdc12d94bb7c9b54cbfe351b7ca1b36860008172b91c71"
    inp = {"text": text,
           "voice_a": voice,
           "voice_b": "disabled",
           "voice_c": "disabled"}
    if custom_voice is not None:
        final_inp = {**inp, **{"voice_a": "custom_voice", "custom_voice": voice_file}}
        with open(custom_voice, "rb") as voice_file:
            return replicate.run(model, input=final_inp)
    else:
        return replicate.run(model, input=inp)

def read_script(script, file_prefix="post"):
    pbar = tqdm.tqdm(total = len(script))
    for ix, block in enumerate(script):
        if isinstance(block, dict) and "silence" in block:
            continue
        if block not in CACHE:
            audio_url = read(block)
            fname = f"{file_prefix}-{str(ix).zfill(5)}.mp3"
            download_mp3(fname, audio_url)
            CACHE[block] = {"url": audio_url, "file": fname}
        pbar.update(1)
    pbar.close()
    return script

def read_complete_p(script):
    for block in script:
        if isinstance(block, str) and block not in CACHE:
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
        if str(block) in CACHE:
            inputs.append(CACHE[str(block)]['file'])
        elif isinstance(block, dict):
            fname = silence(block['silence'])
            CACHE[str(block)] = {'file': fname}
            inputs.append(fname)
    check_output([SOX] + inputs + [output])
    return output

def read_thing(target, output=None):
    try:
        script = script_from_(target)
        script = normalize_script(script)
        if output is None:
            output = tempfile.mkstemp(".mp3", prefix="read-audio-", dir=".")[1]
        prefix, ext = os.path.splitext(output)
        while not read_complete_p(script):
            read_script(script, file_prefix=prefix)
        return cat(script, output)
    except Exception as e:
        print(f"Exception: {e}")
        return None

if __name__ == "__main__":
    for target in sys.argv[1:]:
        print(f"Reading {target}...")
        res = read_target(target)
        if res is None:
            print("  fail")
        else:
            print("  done")
