"""Run in CI: build static text embeddings; upload only the vision weights."""
import json
import sys
import urllib.request
from pathlib import Path

import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from visual_filter import PROMPTS

root = Path(sys.argv[1])
root.mkdir(parents=True, exist_ok=True)
revision = '6ef1ebc8b0766a7a8d11b146462c99cdf74dd22d'
base = f'https://huggingface.co/Xenova/clip-vit-base-patch32/resolve/{revision}/'
for filename, remote in [('vision.onnx', 'onnx/vision_model_quantized.onnx'),
                         ('text.onnx', 'onnx/text_model_quantized.onnx'),
                         ('tokenizer.json', 'tokenizer.json')]:
    target = root / filename
    if not target.is_file():
        print('Downloading ' + remote, flush=True)
        urllib.request.urlretrieve(base + remote, target)

tok = Tokenizer.from_file(str(root / 'tokenizer.json'))
tok.enable_truncation(max_length=77)
tok.enable_padding(length=77, pad_id=49407, pad_token='<|endoftext|>')
encoded = tok.encode_batch(PROMPTS)
options = ort.SessionOptions()
options.intra_op_num_threads = 2
session = ort.InferenceSession(str(root / 'text.onnx'), sess_options=options,
                               providers=['CPUExecutionProvider'])
values = {'input_ids': np.array([e.ids for e in encoded], dtype=np.int64),
          'attention_mask': np.array([e.attention_mask for e in encoded], dtype=np.int64)}
inputs = {i.name: values[i.name] for i in session.get_inputs()}
vectors = session.run(['text_embeds'], inputs)[0]
vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
np.save(root / 'prompts.npy', vectors)
print('Text embeddings ready:', vectors.shape)
