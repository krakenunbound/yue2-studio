"""Exercise HTTP validation, single-flight rejection, cancellation and recovery."""
import concurrent.futures
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = 'http://127.0.0.1:7794/api/assist/'

def post(path, payload):
    started = time.monotonic()
    request = urllib.request.Request(BASE + path, data=json.dumps(payload).encode(), headers={'Content-Type':'application/json'})
    try:
        with urllib.request.urlopen(request, timeout=100) as response:
            return response.status, json.load(response), round(time.monotonic()-started, 2)
    except urllib.error.HTTPError as error:
        return error.code, json.load(error), round(time.monotonic()-started, 2)

rows = []
for name, path, payload, expected in [
    ('empty-compose', 'writing', {'action':'compose'}, 400),
    ('empty-optimize', 'writing', {'action':'optimize'}, 400),
    ('empty-translate', 'writing', {'action':'translate','lyrics':'[Verse]'}, 400),
    ('empty-effect', 'writing', {'action':'effect'}, 400),
    ('invalid-action', 'writing', {'action':'bad'}, 422),
    ('oversized-idea', 'writing', {'action':'generate','idea':'x'*4001}, 422),
    ('oversized-context', 'writing', {'action':'translate','lyrics':'[Verse]\n'+'Long lyric line\n'*800}, 400),
    ('bad-chat-role', 'chat', {'messages':[{'role':'assistant','content':'Hello'}]}, 400),
]:
    status, result, elapsed = post(path, payload)
    rows.append({'case':name,'passed':status==expected,'status':status,'seconds':elapsed,'output':result})

with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
    active = pool.submit(post, 'writing', {'action':'generate','idea':'A long original folk song about restoring a fishing boat, with two verses and a chorus','description':'English acoustic folk'})
    time.sleep(1)
    status, result, elapsed = post('writing', {'action':'effect','description':'A door slams'})
    rows.append({'case':'overlap-rejected','passed':status==409,'status':status,'seconds':elapsed,'output':result})
    status, result, elapsed = post('abort', {})
    rows.append({'case':'abort-responsive','passed':status==200 and elapsed<3,'status':status,'seconds':elapsed})
    status, result, elapsed = active.result(timeout=95)
    rows.append({'case':'active-request-cancelled','passed':status==502 and 'cancel' in str(result).lower(),'status':status,'seconds':elapsed,'output':result})

status, result, elapsed = post('writing', {'action':'effect','description':'A single wooden door closing softly'})
rows.append({'case':'effect-after-cancel','passed':status==200 and bool(result.get('description')),'status':status,'seconds':elapsed,'output':result})
status, result, elapsed = post('chat', {'messages':[{'role':'user','content':'Hello'}]})
rows.append({'case':'chat-after-cancel','passed':status==200 and result.get('ready') is False,'status':status,'seconds':elapsed,'output':result})
with urllib.request.urlopen('http://192.168.1.115:11434/api/ps', timeout=5) as response:
    loaded = json.load(response)['models']
rows.append({'case':'model-still-resident','passed':any(m['name']=='gemma3:4b' and m['size_vram']>0 for m in loaded)})
target = Path(__file__).resolve().parents[1]/'outputs'/'ai-qa'/'controls.json'
target.parent.mkdir(parents=True,exist_ok=True)
target.write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
for row in rows:
    print(json.dumps({k:v for k,v in row.items() if k!='output'}),flush=True)
raise SystemExit(int(any(not row['passed'] for row in rows)))
