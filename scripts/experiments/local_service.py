"""Owned llama-server lifecycle for experiment scripts (extracted from native_model_pilot, W0-10).

Starts the frozen Agents-A1-4B server only when the port is free, verifies that any existing
listener runs exactly the frozen model/server paths, and stops only a process it started.
The server argv is unchanged from the native/G1/G2 pilots, so runtimes stay comparable.
"""
import hashlib
import json
from pathlib import Path
import socket
import subprocess
import time
import urllib.request

import os

# Overridable for other hosts (e.g. Kaggle); the same GGUF file is verified by sha256 there.
MODEL=Path(os.environ.get('KAGE_MODEL_PATH', Path.home()/'.kage/models/agents-a1-4b/Agents-A1-4B-Q4_K_M.gguf'))
SERVER=Path(os.environ.get('KAGE_LLAMA_SERVER', '/opt/homebrew/bin/llama-server'))
# P4-L3: optional LoRA adapter (GGUF) applied on top of the frozen base model.
LORA=os.environ.get('KAGE_LORA')


def write_json(path,value):
    Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')


def file_hash(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block)
    return digest.hexdigest()


def server_argv(port):
    return [str(SERVER),'-m',str(MODEL),'--alias','agents-a1-4b','--jinja','--host','127.0.0.1','--port',str(port),
            '-ngl','99','--flash-attn','auto','-c','8192','-np','1','-n','1024','--reasoning','off',
            '--cache-type-k','q8_0','--cache-type-v','q8_0','--temp','0.85','--top-p','0.95','--top-k','20','--presence-penalty','1.1',
            # llama.cpp's host-RAM prompt cache defaults to 8 GiB per server; four servers filled Kaggle's
            # 32 GB and got killed (E-1 v5/v9), and it made the Mac sluggish. Outputs are unaffected.
            '--cache-ram','0']+(['--lora',LORA] if LORA else [])


def occupied(port):
    with socket.socket() as sock:
        sock.settimeout(.5)
        return sock.connect_ex(('127.0.0.1',port))==0


def get_json(port,path):
    with urllib.request.urlopen(f'http://127.0.0.1:{port}{path}',timeout=3) as response:
        return json.loads(response.read())


def server_version(output):
    """Bound the optional CLI probe; preserve its actual outcome and log evidence."""
    try:
        probe=subprocess.run([str(SERVER),'--version'],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=3)
        result={'status':'exited','returncode':probe.returncode,'output':probe.stdout.strip()}
    except subprocess.TimeoutExpired as exc:
        partial=exc.output or ''
        if isinstance(partial,bytes):partial=partial.decode('utf-8',errors='replace')
        result={'status':'timeout','timeout_s':3,'output':partial.strip()}
    except OSError as exc:
        result={'status':'error','error':f'{type(exc).__name__}: {exc}'}
    log=Path(output)/'server.log'
    result['log_build_info']=[line for line in log.read_text(errors='replace').splitlines() if line.startswith('build:')] if log.exists() else []
    return result


class LocalService:
    """Starts only when absent; stops only the process created by this context."""
    def __init__(self,port,output):self.port=port;self.output=output;self.process=None;self.log=None
    def __enter__(self):
        argv=server_argv(self.port)
        if not occupied(self.port):
            self.log=(self.output/'server.log').open('a')   # keep earlier attempts' logs (crash evidence)
            self.process=subprocess.Popen(argv,stdout=self.log,stderr=subprocess.STDOUT)
        try:
            deadline=time.monotonic()+180
            while True:
                if self.process and self.process.poll() is not None:raise RuntimeError('owned llama server exited during startup')
                try:
                    health=get_json(self.port,'/health')
                    if health.get('status')=='ok':break
                except Exception:
                    pass
                if time.monotonic()>=deadline:raise RuntimeError('local llama server not healthy before startup deadline')
                time.sleep(.5)
            # Existing listeners require observable process provenance, not alias alone.
            listener=subprocess.check_output(['lsof','-nP','-iTCP:'+str(self.port),'-sTCP:LISTEN','-t'],text=True).splitlines()
            pids=sorted(set(listener))
            if len(pids)!=1:raise RuntimeError('local service owner could not be uniquely identified')
            actual_argv=subprocess.check_output(['ps','-p',pids[0],'-o','command='],text=True).strip()
            if str(MODEL) not in actual_argv or str(SERVER) not in actual_argv:
                raise RuntimeError('existing service does not match frozen model/server paths')
            models=get_json(self.port,'/v1/models')
            if not any(m.get('id')=='agents-a1-4b' for m in models.get('data',[])):
                raise RuntimeError('local server model alias mismatch')
            self.runtime={'model_path':str(MODEL),'model_sha256':file_hash(MODEL),
                          'server_path':str(SERVER),'server_sha256':file_hash(SERVER.resolve()),
                          'server_version':server_version(self.output),
                          'server_argv':argv,'actual_server_command':actual_argv,'server_pid':int(pids[0]),
                          'owned_service':self.process is not None,'health':health,'models':models,'port':self.port}
            return self
        except BaseException:
            self.__exit__(None,None,None)
            raise
    def __exit__(self,*args):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:self.process.wait(timeout=15)
            except subprocess.TimeoutExpired:self.process.kill();self.process.wait(timeout=5)
        if self.log:self.log.close()
        write_json(self.output/'service-cleanup.json',{'owned_service':self.process is not None,
                                                      'owned_service_stopped':self.process is not None and self.process.poll() is not None})
