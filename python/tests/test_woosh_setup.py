import hashlib
import io
from pathlib import Path
from types import SimpleNamespace
import zipfile
import pytest
import woosh_setup


def test_archive_cannot_escape_destination(tmp_path):
    archive=tmp_path/'bad.zip'
    with zipfile.ZipFile(archive,'w') as z: z.writestr('../outside.txt','bad')
    with pytest.raises(ValueError, match='unsafe'):
        woosh_setup.unpack(SimpleNamespace(_check_cancel=lambda:None),archive,tmp_path/'target')
    assert not (tmp_path/'outside.txt').exists()


def test_clean_woosh_install_builds_private_python_312_runtime(tmp_path, monkeypatch):
    payloads={}
    def archive(name, members):
        stream=io.BytesIO()
        with zipfile.ZipFile(stream,'w') as z:
            for path,data in members.items():z.writestr(path,data)
        path='outputs/'+name+'.zip';payloads[path]=stream.getvalue()
        return {'path':path,'bytes':len(payloads[path])}
    weights=archive('weights',{'checkpoints/weights/weights.safetensors':b'weights'})
    source=archive('source',{'Woosh-pinned/pyproject.toml':b'[project]','Woosh-pinned/LICENSE.MIT':b'license'})
    spec={'archives':[weights],'source':source}
    monkeypatch.setattr(woosh_setup,'manifest',lambda:spec)
    calls=[]
    runtime=tmp_path/'python/woosh_runtime/Scripts/python.exe'
    def run(key,command,phase,**kwargs):
        calls.append((command,kwargs))
        if phase=='Checking Woosh runtime': raise OSError('not installed')
    def download(key,entry,*args):
        path=tmp_path/entry['path'];path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(payloads[entry['path']])
    manager=SimpleNamespace(ROOT=tmp_path,OUTPUTS_ROOT=tmp_path/'outputs',CATALOG={'woosh':[{'path':'models/sound_effects/woosh/checkpoints/weights/weights.safetensors'}]},_check_cancel=lambda:None,_verified=lambda *a:False,target=lambda entry:tmp_path/entry['path'],_download=download,_update=lambda *a,**kw:None,runtime_python=lambda key:runtime,_run=run)
    woosh_setup.install(manager)
    assert (tmp_path/'models/sound_effects/woosh/checkpoints/weights/weights.safetensors').read_bytes()==b'weights'
    sync=next((cmd,kwargs) for cmd,kwargs in calls if 'sync' in cmd)
    assert '3.12' in sync[0] and 'cuda' in sync[0]
    assert sync[1]['extra_env']['UV_PROJECT_ENVIRONMENT']==str(runtime.parent.parent)
    assert (tmp_path/'models/sound_effects/woosh/LICENSE.MIT').is_file()
