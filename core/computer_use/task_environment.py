"""Trusted resettable HTTP fixtures and independent browser-result checkpoints."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import html
import json
from pathlib import Path
import threading

_CHECKPOINT_LOCK = threading.Lock()


def render_fixture(fixture):
    kind=fixture['kind']
    esc=lambda value:html.escape(str(value),quote=True)
    if kind in ('profile','invoice','preferences'):
        fields=[]
        for field in fixture['fields']:
            checkbox=kind=='preferences'
            checked=' checked' if checkbox and field['initial'] else ''
            fields.append(f'<label>{esc(field["label"])}<input name="{esc(field["name"])}" aria-label="{esc(field["label"])}" type="{"checkbox" if checkbox else "text"}"{checked}></label>')
        table=''
        if kind=='invoice':
            table='<table><tr><th>Item</th><th>Quantity</th><th>Unit price</th></tr>'+''.join(f'<tr><td>{esc(r["item"])}</td><td>{r["qty"]}</td><td>{r["price"]}</td></tr>' for r in fixture['rows'])+'</table>'
        body=table+'<form>'+''.join(fields)+f'<button>{esc(fixture["submit"])}</button></form>'
        script='''document.querySelector('form').onsubmit=async e=>{e.preventDefault(); const result={};
        for(const input of document.querySelectorAll('input')) result[input.name]=input.type==='checkbox' ? input.checked : input.value;
        if(KIND==='invoice') result.total=Number(result.total);
        await save(result);};'''.replace('KIND',json.dumps(kind))
    elif kind=='catalog':
        body=f'<label>{esc(fixture["query_label"])}<input name="city" aria-label="{esc(fixture["query_label"])}"></label><label>{esc(fixture["category_label"])}<input type="checkbox" id="category" aria-label="{esc(fixture["category_label"])}"></label><button id="apply">{esc(fixture["apply_label"])}</button><section id="items"></section>'
        # Public catalog data is page content. It contains no checker/expected id.
        script='''const items=ITEMS;let category=false,applied=null;
        function show(rows){const root=document.querySelector('#items');root.replaceChildren();
        for(const item of rows){const row=document.createElement('article');row.textContent=item.name+' | '+item.city+' | '+item.category+' | '+item.price;
        const button=document.createElement('button');button.textContent='Choose '+item.name;
        button.onclick=()=>save({property_id:item.id,city:applied?.city??'',category:applied?.category??''});row.append(button);root.append(row);}}
        document.querySelector('#category').onclick=e=>{category=e.target.checked;};
        document.querySelector('#apply').onclick=()=>{applied={city:document.querySelector('input').value,category:category?CATEGORY:''};
        show(items.filter(i=>i.city===applied.city && (!applied.category || i.category===applied.category)));};show(items);'''.replace('ITEMS',json.dumps(fixture['items'],ensure_ascii=False).replace('<','\\u003c')).replace('CATEGORY',json.dumps(fixture['category']))
    else:
        raise ValueError('unknown browser fixture kind')
    common="""async function save(record){const response=await fetch('/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(record)});document.querySelector('[data-result]').textContent=JSON.stringify(await response.json());}"""
    return f'<!doctype html><meta charset="utf-8"><title>{esc(fixture["title"])}</title><style>label,article{{display:block;margin:12px}}table td{{padding:8px}}</style><h1>{esc(fixture["title"])}</h1>{body}<pre data-result></pre><script>{common}{script}</script>'.encode()


@contextmanager
def browser_task_server(fixture,workspace):
    workspace=Path(workspace)
    state={'saved':None,'posts':0}
    page=render_fixture(fixture)
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            with _CHECKPOINT_LOCK:
                data=json.dumps({'record':state['saved'],'posts':state['posts']}).encode() if self.path=='/record' else page
            self.send_response(200);self.send_header('Content-Type','application/json' if self.path=='/record' else 'text/html; charset=utf-8')
            self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
        def do_POST(self):
            if self.path!='/save': self.send_error(404);return
            try:
                record=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            except (ValueError,KeyError): self.send_error(400);return
            with _CHECKPOINT_LOCK:
                backend={'record':record,'posts':state['posts']+1}
                # Revoke old proof before committing a new backend record. A
                # killed worker must never leave a passing stale checkpoint.
                atomic_json(workspace/'browser-check.json',backend|{'readback_matches_backend':False})
                state['saved']=record;state['posts']=backend['posts']
                atomic_json(workspace/'backend.json',backend)
            data=json.dumps(record,ensure_ascii=False).encode()
            self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
        def log_message(self,*args): pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}',state
    finally:
        server.shutdown();server.server_close();thread.join()


def atomic_json(path,value):
    temporary=path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2))
    temporary.replace(path)


async def checkpoint(page,url,workspace):
    backend=await (await page.request.get(url+'/record',timeout=3000)).json()
    try:
        text=await page.locator('[data-result]').inner_text(timeout=1000)
        rendered=json.loads(text)
    except Exception:
        rendered=None
    with _CHECKPOINT_LOCK:
        backend_path=Path(workspace)/'backend.json'
        current=json.loads(backend_path.read_text()) if backend_path.exists() else {'record':None,'posts':0}
        # A POST may land while the awaited HTTP/DOM reads are in flight.
        # In that case preserve the latest backend and fail closed until reread.
        check=current|{'readback_matches_backend':backend==current and current['record'] is not None and rendered==current['record']}
        atomic_json(Path(workspace)/'browser-check.json',check)
    return check
