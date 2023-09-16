import re
from bs4 import BeautifulSoup
from io import BytesIO
import markdown
import nltk.data
import os

import models
import state

TOK = nltk.data.load("tokenizers/punkt/english.pickle")

def _sanitize(txt):
    return re.sub("’", "'", re.sub("[\[\]]", "", txt.strip()))

def _image_text(url):
    caption = state.get(url)
    if caption is not None:
        return caption

    img = BytesIO(requests.get(url).content)
    caption = models.caption_image(img)
    state.put(url, caption)
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

def _script_from_(thing):
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

def script_from(target):
    return normalize_script(_script_from_(target))
