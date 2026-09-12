"""Check attention equivalence and optionally full-model long-sequence memory.
Run with python/runtime/Scripts/python.exe scripts/check_yue2_memory.py --gpu
The GPU fixture uses synthetic codec tokens, not a generated song.
"""
from pathlib import Path
import sys, json, time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'python'))
import torch
from yue2.nar import attention
from yue2_memory import synthesize_bounded, QUERY_CHUNK_SIZE

def equivalence():
    torch.manual_seed(17)
    for causal in (False, True):
        q=torch.randn(535,8,16)
        k=torch.randn(535 if causal else 681,2,16)
        v=torch.randn_like(k)
        expected=attention(q,k,v,causal=causal,backend='math',query_chunk_size=1000)
        actual=attention(q,k,v,causal=causal,backend='math',query_chunk_size=QUERY_CHUNK_SIZE)
        torch.testing.assert_close(actual,expected,rtol=1e-5,atol=1e-6)
    print('PASS: tiled attention matches untiled attention, including causal offsets and grouped heads',flush=True)

def forwarding():
    from types import SimpleNamespace
    from unittest.mock import patch
    from yue2.pipeline import SymbolicPlan, SemanticResult
    from yue2.protocol import SongRequest, GenerationConfig, token_prefixes
    tokenizer=SimpleNamespace(encode=lambda text: [11,12])
    request=SongRequest(style='folk',lyrics='hello',cot='off',seed=12)
    plan=SymbolicPlan(request,None,[],token_prefixes(request,tokenizer,[]))
    semantic=SemanticResult(plan,list(range(9000)),{},False)
    config=GenerationConfig(ode_steps=32)
    model=object()
    pipe=SimpleNamespace(backend='torch-eager',quantization='none',tokenizer=tokenizer,
                         generation_config=config,offload_ar=False,_load_model=lambda **kw: model)
    cancel=lambda: False
    progress=lambda n,t: None
    with patch('yue2.nar.synthesize',return_value=torch.zeros(9000,64)) as solver:
        result=synthesize_bounded(pipe,semantic,cancelled=cancel,on_progress=progress)
    args,kwargs=solver.call_args
    assert args==(model,plan.prefix,semantic.tokens,12)
    assert kwargs['steps']==32 and kwargs['context']==24576
    assert kwargs['query_chunk_size']==256 and kwargs['cancelled'] is cancel and kwargs['on_progress'] is progress
    assert result.shape==(9000,64)
    semantic.plan.prefix=[99]
    with patch('yue2.nar.synthesize') as solver:
        try: synthesize_bounded(pipe,semantic)
        except ValueError: pass
        else: raise AssertionError('Invalid prefix was accepted')
        solver.assert_not_called()
    print('PASS: full token sequence, seed, 32 steps, cancellation and prefix validation preserved',flush=True)

def stress():
    import numpy as np
    from yue2 import YuE2Pipeline
    from yue2.pipeline import SemanticResult
    from yue2.protocol import GenerationConfig
    root=Path(__file__).resolve().parents[1]
    pipe=YuE2Pipeline.from_pretrained(root,vae=root/'models/YuE2-Vae',device='cuda',backend='torch-eager',memory_budget_gib=21.6,progress=False)
    try:
        plan=pipe.plan(style='Acoustic folk',lyrics='[Verse]\nMemory validation',cot='full',abc='C D E F G A B c | '*400,seed=123)
        semantic=SemanticResult(plan,[i%32768 for i in range(9000)],{},False)
        # Two midpoint iterations exercise all repeated solver allocations.
        # Production remains at the user's configured 32-step default.
        pipe.generation_config=GenerationConfig(ode_steps=32 if '--full' in sys.argv else 2)
        torch.cuda.reset_peak_memory_stats()
        started=time.monotonic()
        print(json.dumps({'prefix_tokens':len(plan.prefix),'codec_tokens':len(semantic.tokens),'query_batch':QUERY_CHUNK_SIZE,'allocation_limit_gib':19.6}),flush=True)
        latent=synthesize_bounded(pipe,semantic,on_progress=lambda n,t: print(f'Synthesis step {n}/{t}',flush=True))
        assert latent.shape==(9000,64) and np.isfinite(latent).all()
        peak=torch.cuda.max_memory_allocated()/2**30
        print(json.dumps({'synthesis_peak_gib':peak,'seconds':time.monotonic()-started}),flush=True)
        audio=pipe.decode(latent)
        assert audio.ndim==2 and audio.shape[1]==2 and np.isfinite(audio).all()
        result={'steps':pipe.generation_config.ode_steps,'synthetic_codec_tokens':9000,'prefix_tokens':len(plan.prefix),'synthesis_peak_gib':peak,'total_peak_gib':torch.cuda.max_memory_allocated()/2**30,'audio_seconds':len(audio)/48000,'seconds':time.monotonic()-started}
        (root/('docs/memory-validation-full.json' if '--full' in sys.argv else 'docs/memory-validation.json')).write_text(json.dumps(result,indent=2))
        print('PASS: full-model long-sequence synthesis and stereo decode '+json.dumps(result),flush=True)
    finally:
        pipe.close()

equivalence()
forwarding()
if '--gpu' in sys.argv: stress()
