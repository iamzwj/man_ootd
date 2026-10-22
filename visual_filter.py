"""Visual screening. Photos are decoded in RAM and never written to disk."""
import io
import json
import os
import threading
from collections import OrderedDict
from pathlib import Path

PROMPTS = [
    'a cinematic editorial photograph of an adult man with atmospheric lighting',
    'an artistic photograph of a man outdoors with beautiful natural light and composition',
    'a moody film photograph of a man in everyday life',
    'a fine art portrait photograph of an adult man with expressive light and shadows',
    'a real portrait photograph of a woman',
    'a real photograph of a girl',
    'an anime drawing of a boy, cartoon illustration',
    'an anime drawing of a girl, cartoon illustration',
    'a drawing, painting, comic, or digital illustration of a person',
    'a 3D rendered game character, a doll or a virtual person',
    'a plain corporate ID passport photograph with flat lighting',
    'a generic commercial advertising stock photograph of an office worker',
    'a product photograph of clothing without a person, flat lay or mannequin',
    'a collage of multiple outfits and products, a fashion infographic',
    'a landscape photograph without a person',
    'a photograph of a child',
    'a cinematic artistic portrait photograph of a woman with dramatic lighting',
    'an artistic photograph of a woman in a park or garden',
    'a photograph of a couple, a man and a woman together',
    'a photograph of food, a meal, or a restaurant table',
    'a screenshot with text or a fashion magazine cover',
]
ROOT = Path(os.environ.get('OOTD_VISION_ROOT', '/var/lib/ootd/vision'))
_session = None
_vectors = None
_lock = threading.Lock()
_cache = OrderedDict()
_metadata = {}


def ready():
    return all((ROOT / x).is_file() for x in ['vision.onnx', 'prompts.npy'])


def load():
    global _session, _vectors
    if _session is not None:
        return
    import numpy as np
    import onnxruntime as ort
    options = ort.SessionOptions()
    options.intra_op_num_threads = 2
    options.inter_op_num_threads = 1
    _session = ort.InferenceSession(str(ROOT / 'vision.onnx'), sess_options=options,
                                   providers=['CPUExecutionProvider'])
    _vectors = np.load(ROOT / 'prompts.npy', allow_pickle=False)


def inspect_bytes(body):
    import numpy as np
    from PIL import Image, ImageOps
    Image.MAX_IMAGE_PIXELS = 30_000_000
    with Image.open(io.BytesIO(body)) as source:
        img = ImageOps.exif_transpose(source).convert('RGB')
        w, h = img.size
        small = list(img.convert("L").resize((9, 8)).getdata())
        fingerprint = format(sum((small[y*9+x] > small[y*9+x+1]) << (y*8+x) for y in range(8) for x in range(8)), "016x")
        scale = 224 / min(w, h)
        img = img.resize((round(w * scale), round(h * scale)), Image.Resampling.BICUBIC)
        left, top = (img.width - 224) // 2, (img.height - 224) // 2
        img = img.crop((left, top, left + 224, top + 224))
        pixels = np.asarray(img, dtype=np.float32) / 255
    pixels = (pixels - np.array([.48145466, .4578275, .40821073], dtype=np.float32)) / np.array([.26862954, .26130258, .27577711], dtype=np.float32)
    pixels = np.transpose(pixels, (2, 0, 1))[None].astype(np.float32)
    with _lock:
        load()
        embedding = _session.run(['image_embeds'], {'pixel_values': pixels})[0][0]
    embedding /= np.linalg.norm(embedding)
    scores = _vectors @ embedding
    male = float(max(scores[:4]))
    other = float(max(scores[4:]))
    # Positive margin rather than blindly accepting the top label.
    return male >= .22 and male - other >= .012, round(male - other, 4), PROMPTS[int(np.argmax(scores))], fingerprint, w, h


def accept(url, read):
    with _lock:
        if url in _cache:
            _cache.move_to_end(url)
            return _cache[url]
    if not ready():
        return False
    try:
        accepted, margin, label, fingerprint, width, height = inspect_bytes(read(url))
        with _lock:
            _metadata[url] = {"fingerprint": fingerprint, "width": width, "height": height}
        print(json.dumps({'visual': accepted, 'margin': margin, 'label': label}), flush=True)
    except Exception as exc:
        print('visual screening unavailable: ' + type(exc).__name__, flush=True)
        return False
    with _lock:
        _cache[url] = accepted
        while len(_cache) > 2500:
            _cache.popitem(last=False)
    return accepted


def metadata(url):
    with _lock:
        return dict(_metadata.get(url, {}))
