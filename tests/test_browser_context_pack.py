"""Projection must keep executable current state and immutable old evidence."""
import copy
import hashlib
import json
from core.computer_use.context_pack import pack_browser_messages


def observation(oid):
    return {'observation_id':oid,'source':'dom','surface_id':'page-1','targets':[{'target_ref':'e1','label':'Save','checked':False}],'text':'实际页面'*400}


def test_old_dom_archived_but_latest_error_and_native_links_survive(tmp_path):
    old=observation('old');latest=observation('current')
    messages=[{'role':'system','content':'Browser policy'},
        {'role':'user','content':'Save my settings\nInitial browser observation supplied by runtime:\n'+json.dumps(old,ensure_ascii=False)},
        {'role':'assistant','content':'click','tool_calls':[{'id':'call-1','type':'function','function':{'name':'browser_act','arguments':'{"target_ref":"e1"}'}}]},
        {'role':'tool','tool_call_id':'call-1','content':'[Tool: browser_act] '+json.dumps({'success':False,'error':'StaleObservation','message':'reobserve','outcome':'rejected','observation':old})},
        {'role':'assistant','content':'observe','tool_calls':[{'id':'call-2','type':'function','function':{'name':'browser_observe','arguments':'{}'}}]},
        {'role':'tool','tool_call_id':'call-2','content':'[Tool: browser_observe] '+json.dumps({'success':True,'observation':latest})}]
    original=copy.deepcopy(messages)
    packed,stats=pack_browser_messages(messages,tmp_path)
    assert messages==original
    assert packed[0]==original[0] and packed[2]==original[2] and packed[4:]==original[4:]
    assert packed[1]['content'].startswith('Save my settings\n')
    result=json.loads(packed[3]['content'].split('] ',1)[1])
    assert result['error']=='StaleObservation' and result['outcome']=='rejected'
    assert packed[3]['tool_call_id']=='call-1' and 'observation' not in result
    ref=result['observation_archived']
    raw=(tmp_path/ref['path']).read_bytes()
    assert json.loads(raw)==old and hashlib.sha256(raw).hexdigest()==ref['sha256']
    assert stats['archived_observations']==2
    assert len(json.dumps(packed).encode())<len(json.dumps(original).encode())
    assert json.loads((tmp_path/stats['source_path']).read_text())==original


def test_no_fresh_observation_leaves_messages_intact(tmp_path):
    messages=[{'role':'user','content':'Task\nInitial browser observation supplied by runtime:\n'+json.dumps(observation('only'))},
        {'role':'tool','tool_call_id':'failure','content':'[Tool: browser_act] {"success":false,"error":"BrowserError","observation_error":"Page closed"}'},
        {'role':'assistant','content':'Malformed unrelated {text'}]
    packed,stats=pack_browser_messages(messages,tmp_path)
    assert packed==messages and stats['archived_observations']==0


def test_large_current_dom_still_hits_original_wire_limit_without_network(tmp_path):
    import pytest
    from core.computer_use.context_pack import BrowserContextProvider
    from scripts.experiments.task_suite import RecordedLocalProvider
    current=observation('current');current['text']='大页面'*10000
    messages=[{'role':'user','content':'Task\nInitial browser observation supplied by runtime:\n'+json.dumps(current)}]
    trace=tmp_path/'network-responses.jsonl'
    model=RecordedLocalProvider(trace,api_key='test',model_name='deepseek-flash',base_url='http://127.0.0.1:1',thinking=False,output_limit=1024)
    with pytest.raises(RuntimeError,match='teacher input byte cap reached'):
        BrowserContextProvider(model,tmp_path).generate(messages)
    assert not trace.exists()
    evidence=json.loads((tmp_path/'teacher-context-pack.jsonl').read_text())
    assert evidence['archived_observations']==0
    assert json.loads((tmp_path/evidence['source_path']).read_text())==messages
