"""仅用于章节出题的本地模型；独立进程推理，完成后释放内存。"""
import json
import os
import re
import subprocess
import sys
import threading
from pathlib import Path

MODEL_PATH = r'D:\学习\大四上\模型存放处\qwen3-4B-Instruct-2507'
_LOCK = threading.Lock()


class LocalQwenClient:
    model = 'Qwen3-4B-Instruct-2507-local'

    def stream_chat(self, messages, temperature=0.8, max_tokens=4096, on_finish=None):
        messages = [dict(message) for message in messages]
        if messages and messages[0].get('role') == 'system':
            messages[0]['content'] += (
                '\n出题依据是lecture中的讲解正文。sources为空只表示没有教材引用，'
                '并不表示没有出题依据；此时citation_ids填[]，仍须根据lecture生成count道题。'
                '不要返回空数组。answer必须是单个大写字母A、B、C或D。')
        if not Path(MODEL_PATH, 'config.json').is_file():
            raise ValueError('找不到本地 Qwen 模型，请检查模型存放目录')
        if not _LOCK.acquire(blocking=False):
            raise ValueError('本地模型正在出题，请等待当前任务完成')
        try:
            try:
                result = subprocess.run(
                    [sys.executable, str(Path(__file__).resolve()), str(os.getpid())],
                    input=json.dumps(dict(messages=messages, temperature=min(temperature, 0.4),
                                         max_tokens=max_tokens)),
                    capture_output=True, encoding='utf-8', errors='replace', timeout=600,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            except subprocess.TimeoutExpired as exc:
                raise ValueError('本地出题超过10分钟，已停止。请减少小节内容后重试') from exc
            if result.returncode:
                raise ValueError('本地 Qwen 加载或推理失败（不会改用云端）：' + result.stderr[-1200:])
            payload = json.loads(result.stdout)
            self.last_metrics = {key: payload.get(key) for key in ('quantization', 'devices', 'peak_gpu_mib')}
            text = payload['text']
            # 小模型偶尔在完整JSON数组后多写闭括号；仅去掉多余闭括号，
            # 不补全截断内容、不改题目字段，仍交给原有出题校验检查。
            if payload['finish'] == 'stop':
                candidate = re.sub(r'^```(?:json)?\s*|\s*```$', '', text.strip())
                try:
                    value, end = json.JSONDecoder().raw_decode(candidate)
                    if isinstance(value, list) and re.fullmatch(r'[\s\]}]*', candidate[end:]):
                        text = json.dumps(value, ensure_ascii=False)
                except ValueError:
                    pass
            yield text
            if on_finish:
                on_finish(payload['finish'])
        finally:
            _LOCK.release()


def run_worker():
    # 网页关闭导致主服务退出时，一并释放推理进程和显存。
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        handle = kernel.OpenProcess(0x00100000, False, int(sys.argv[1]))
        if not handle:
            raise RuntimeError('无法监测主服务状态')
        def watch_parent():
            kernel.WaitForSingleObject(handle, 0xFFFFFFFF)
            os._exit(0)
        threading.Thread(target=watch_parent, daemon=True).start()
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
    if not torch.cuda.is_available():
        raise RuntimeError('本地4-bit模式需要可用的NVIDIA显卡，请检查CUDA版PyTorch')
    payload = json.load(sys.stdin)
    tokenizer = AutoTokenizer.from_pretrained(MODEL_PATH, local_files_only=True)
    text = tokenizer.apply_chat_template(payload['messages'], tokenize=False,
                                        add_generation_prompt=True)
    inputs = tokenizer(text, return_tensors='pt')
    if inputs.input_ids.shape[1] > 8192:
        raise ValueError('当前小节及历史题目超过本地版8192词元输入上限，请选较短小节')
    compute_dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
    quantization = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type='nf4',
                                     bnb_4bit_use_double_quant=True,
                                     bnb_4bit_compute_dtype=compute_dtype)
    kwargs = dict(local_files_only=True, torch_dtype=compute_dtype,
                  quantization_config=quantization, device_map={'': 0})
    model = AutoModelForCausalLM.from_pretrained(MODEL_PATH, **kwargs).eval()
    if not getattr(model, 'is_loaded_in_4bit', False):
        raise RuntimeError('模型未成功以4-bit加载，已停止推理')
    inputs = inputs.to(model.device)
    with torch.inference_mode():
        output = model.generate(**inputs, max_new_tokens=payload['max_tokens'],
                                do_sample=True, temperature=max(0.1, payload['temperature']),
                                top_p=0.8, top_k=20, pad_token_id=tokenizer.eos_token_id)
    generated = output[0, inputs.input_ids.shape[1]:]
    eos = model.generation_config.eos_token_id
    eos = eos if isinstance(eos, list) else [eos]
    print(json.dumps(dict(text=tokenizer.decode(generated, skip_special_tokens=True),
                          quantization='nf4', devices=sorted({str(p.device) for p in model.parameters()}),
                          peak_gpu_mib=round(torch.cuda.max_memory_allocated() / 1024**2, 1),
                          finish='stop' if generated[-1].item() in eos else 'length'), ensure_ascii=True))


if __name__ == '__main__':
    run_worker()
