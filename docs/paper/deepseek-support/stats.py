import tarfile, json, collections, itertools, random
import numpy as np
from pathlib import Path
ROOT = str(Path(__file__).resolve().parents[3])
OUT = Path(__file__).resolve().parent
RNG=np.random.default_rng(20261027)

def arch(v): return tarfile.open(f'{ROOT}/evidence/kaggle/v{v}-results.tar.gz')
def load_ck(v, contain, arm):
    t=arch(v)
    for m in t.getmembers():
        if m.name.endswith(f'/{arm}/checkpoints.jsonl') and contain in m.name:
            return [json.loads(l) for l in t.extractfile(m).read().decode().splitlines()]
    raise KeyError((v,contain,arm))

def rates(rows_list, cps=('cp0',)):
    acc=collections.defaultdict(list)
    for rows in rows_list:
        for r in rows:
            if r['checkpoint'] in cps: acc[r['task_id']].append(float(r['score']==1))
    return {k:sum(v)/len(v) for k,v in acc.items()}

def signflip(diffs, n_mc=200000):
    d=np.asarray(diffs,float); obs=abs(d.sum())
    if len(d)<=16:
        best=0
        for k in range(2**len(d)):
            signs=np.array([1-2*((k>>i)&1) for i in range(len(d))])
            if abs((d*signs).sum())>=obs-1e-12: best+=1
        return best/(2**len(d))
    signs=RNG.choice([-1.0,1.0],size=(n_mc,len(d)))
    sums=np.abs(signs@d)
    return (sums>=obs-1e-9).mean()

def boot_ci(diffs, n=10000):
    d=np.asarray(diffs,float); idx=RNG.integers(0,len(d),size=(n,len(d)))
    means=d[idx].mean(1); return float(np.quantile(means,.025)),float(np.quantile(means,.975))

def paired(name,a,b,tasks):
    tasks=sorted(tasks); diffs=[a[t]-b[t] for t in tasks]
    return dict(name=name,n_tasks=len(tasks),mean_diff=round(float(np.mean(diffs)),4),
                p_signflip=round(float(signflip(diffs)),6),
                ci95_task_boot=[round(x,4) for x in boot_ci(diffs)],
                positive=int(sum(d>0 for d in diffs)),negative=int(sum(d<0 for d in diffs)),tie=int(sum(d==0 for d in diffs)),
                diffs=[round(float(d),4) for d in diffs],tasks=tasks)

def c4(v,sub,arms):
    return {arm:rates([load_ck(v,sub,arm+'-r%d'%i) for i in (1,2,3)]) for arm in arms}

out={}
# C4 round1
r1=c4(28,'e1/c4',['V1','V2','V2PK','V2PKST'])
prefs=sorted(t for t in r1['V1'] if 'web_prefs' in t)
out['c4_prefs']={a:{t:round(r1[a].get(t),4) for t in prefs} for a in r1}
out['c4_v1_v2']=paired('C4 settings V1->V2',r1['V2'],r1['V1'],prefs)
out['c4_v1_v2pkst']=paired('C4 settings V1->V2PKST',r1['V2PKST'],r1['V1'],prefs)
out['c4_v2_v2pkst']=paired('C4 settings V2->V2PKST',r1['V2PKST'],r1['V2'],prefs)
allt=sorted(r1['V1']); out['c4_all_v1_v2']=paired('C4 all 30 V1->V2',r1['V2'],r1['V1'],allt)
# C4 round2
r2=c4(33,'e1/c4b',['V2PKST','V2PKTST','V2PKTSTCK','R3EV2PKTSTCK'])
inv=sorted(t for t in r2['V2PKST'] if 'web_invoice' in t); prefs2=sorted(t for t in r2['V2PKST'] if 'web_prefs' in t)
out['c4b_prefs']={a:{t:round(r2[a].get(t),4) for t in prefs2} for a in r2}
out['c4b_r3e_invoice']=paired('C4b R3e vs raw winsorized (invoice)',r2['R3EV2PKTSTCK'],r2['V2PKTSTCK'],inv)
out['c4b_r3e_all']=paired('C4b R3e vs raw (all 30)',r2['R3EV2PKTSTCK'],r2['V2PKTSTCK'],sorted(r2['V2PKST']))
# G0
g0={}
for arm in ['a0-test-v2','a0-test-v2-lessons','a0-test-v2-planonly','a0-test-v2-plan','a0-final-v4-plan','a0-baseline-v1']:
    rows=[json.loads(l) for l in open(f'{ROOT}/evidence/reports/g0/{arm}/results.jsonl')]
    acc=collections.defaultdict(list)
    for r in rows: acc[r['task_id']].append(float(r['check']['passed']))
    g0[arm]={k:sum(v)/len(v) for k,v in acc.items()}
var=sorted(g0['a0-test-v2'])
out['g0_arms']={a:dict(sorted(g0[a].items())) for a in g0}
out['g0_plan_vs_none']=paired('G0 plan+adjacent vs none',g0['a0-test-v2-plan'],g0['a0-test-v2'],var)
out['g0_planonly_vs_none']=paired('G0 plan-only vs none',g0['a0-test-v2-planonly'],g0['a0-test-v2'],var)
out['g0_lessons_vs_none']=paired('G0 system lessons vs none',g0['a0-test-v2-lessons'],g0['a0-test-v2'],var)
fr=g0['a0-final-v4-plan']; br=g0['a0-baseline-v1']; tr=sorted(set(fr)&set(br))
out['g0_final_vs_base']=paired('G0 final vs base (10 train tasks, interfaces differ)',fr,br,tr)
out['g0_final_families']={}
for fam,prefixes in {'calculator':['calc_'],'textedit':['te_'],'settings_read':['set_']}.items():
    ts=[t for t in fr if any(t.startswith(p) for p in prefixes)]
    out['g0_final_families'][fam]=dict(tasks=ts,mean=round(float(np.mean([fr[t] for t in ts])),4))
# TextEdit
def g0rate(arm):
    rows=[json.loads(l) for l in open(f'{ROOT}/evidence/reports/g0/{arm}/results.jsonl')]
    acc=collections.defaultdict(list)
    for r in rows: acc[r['task_id']].append(float(r['check']['passed']))
    return {k:sum(v)/len(v) for k,v in acc.items()}
fill={k:v for k,v in g0rate('a0-baseline-v1').items() if k.startswith('te_') and not k.endswith('2')}
fill.update({k:v for k,v in g0rate('a0-test-v2').items() if k.startswith('te_')})
v3=g0rate('a0-te-v3'); v4=g0rate('a0-te-v4'); te=sorted(fill)
out['textedit_fill']=dict(sorted(fill.items())); out['textedit_v3']=dict(sorted(v3.items())); out['textedit_v4']=dict(sorted(v4.items()))
out['textedit_v3_vs_fill']=paired('TextEdit v3 vs fill',v3,fill,te)
out['textedit_v4_vs_fill']=paired('TextEdit v4 vs fill',v4,fill,te)
out['textedit_v4_vs_v3']=paired('TextEdit v4 vs v3',v4,v3,te)
# E-1
a0e=load_ck(6,'e1/A0','A0')
a3=[load_ck(7,'e1/seed1','A3'),load_ck(7,'e1/seed2','A3')]
a4=[load_ck(6,'e1/seed1','A4'),load_ck(6,'e1/seed2','A4')]
a0r={r['task_id']:float(r['score']==1) for r in a0e if r['checkpoint']=='cp0'}
fam={r['task_id']:r['family'] for r in a0e if r['checkpoint']=='cp0'}
a3r=rates(a3,('cp60',)); a4r=rates(a4,('cp60',))
learn={'subset_selection','interval_merge','log_aggregation','csv_transform'}; held={'text_normalize','config_migrate'}
in_t=sorted(t for t in a0r if fam[t] in learn); held_t=sorted(t for t in a0r if fam[t] in held)
out['e1_base']=dict(in_family=[float(sum(a0r[t] for t in in_t)),len(in_t)],held_out=[float(sum(a0r[t] for t in held_t)),len(held_t)])
out['e1_A3_vs_A0']=paired('E-1 A3 vs A0 in-family',a3r,a0r,in_t)
out['e1_A4_vs_A0']=paired('E-1 A4 vs A0 in-family',a4r,a0r,in_t)
out['e1_A3_vs_A4']=paired('E-1 A3 vs A4 in-family',a3r,a4r,in_t)
out['e1_A3_vs_A0_held']=paired('E-1 A3 vs A0 held-out',a3r,a0r,held_t)
# R3 v26
r3ad=rates([load_ck(26,'e1/r3/file',f'L3-r{i}') for i in (1,2,3)])
r3an=rates([load_ck(26,'e1/r3/file',f'A0-r{i}') for i in (1,2,3)])
r3w=rates([load_ck(26,'e1/r3/web',f'L3-r{i}') for i in (1,2,3)])
r3wan=rates([load_ck(26,'e1/r3/web',f'A0-r{i}') for i in (1,2,3)])
r3in=sorted(t for t in r3an if fam.get(t) in learn); r3held=sorted(t for t in r3an if fam.get(t) in held); r3web=sorted(t for t in r3w if any(k in t for k in ('web_invoice','web_prefs','web_catalog')))
out['r3_base']=dict(in_family=[float(sum(r3an[t] for t in r3in)),len(r3in)],held_out=[float(sum(r3an[t] for t in r3held)),len(r3held)],web=[float(sum(r3wan[t] for t in r3web)),len(r3web)])
out['r3_adapter']=dict(in_family=[float(sum(r3ad[t] for t in r3in)),len(r3in)],held_out=[float(sum(r3ad[t] for t in r3held)),len(r3held)],web=[float(sum(r3w[t] for t in r3web)),len(r3web)])
out['r3_in']=paired('R3 in-family',r3ad,r3an,r3in)
out['r3_held']=paired('R3 held-out',r3ad,r3an,r3held)
out['r3_web']=paired('R3 web learned',r3w,r3wan,r3web)
# R3e v32
r3ead=rates([load_ck(32,'e1/ae/file',f'r3e-r{i}') for i in (1,2,3)])
r3ean=rates([load_ck(32,'e1/ae/file','A0-r1')])
out['r3e_base']=dict(in_family=[float(sum(r3ean[t] for t in r3in)),len(r3in)],held_out=[float(sum(r3ean[t] for t in r3held)),len(r3held)])
out['r3e_in']=paired('R3e in-family vs same-session anchor',r3ead,r3ean,r3in)
out['r3e_held']=paired('R3e held-out vs same-session anchor',r3ead,r3ean,r3held)
# R3d for verification
r3dad=rates([load_ck(31,'e1/ae/file',f'r3d-r{i}') for i in (1,2,3)])
out['r3d_in']=paired('R3d in-family vs same-session anchor',r3dad,rates([load_ck(31,'e1/ae/file','A0-r1')]),r3in)
out['r3d_held']=paired('R3d held-out vs same-session anchor',r3dad,rates([load_ck(31,'e1/ae/file','A0-r1')]),r3held)

# ---- R3b, R3c, R3e comparisons on held-out / in-family vs same-session anchor ----
def ae_rates(v, arm):
    return rates([load_ck(v,'e1/ae/file',f'{arm}-r{i}') for i in (1,2,3)])
for tag,v,arm in [('r3b',29,'r3b'),('r3c',30,'r3c'),('r3d',31,'r3d'),('r3e',32,'r3e')]:
    ad=ae_rates(v,arm); an=rates([load_ck(v,'e1/ae/file','A0-r1')])
    out[tag+'_in']=paired(tag+' in-family vs same-session anchor',ad,an,r3in)
    out[tag+'_held']=paired(tag+' held-out vs same-session anchor',ad,an,r3held)
    out[tag+'_base']=dict(in_family=[float(sum(an[t] for t in r3in)),len(r3in)],held_out=[float(sum(an[t] for t in r3held)),len(r3held)])
# R3b vs R3 held-out (different adapters, same task set)
r3bad=ae_rates(29,'r3b')
out['r3b_vs_r3_held']=paired('R3b vs R3 held-out (cross-session)',r3bad,r3ad,r3held)
out['r3b_vs_r3_in']=paired('R3b vs R3 in-family (cross-session)',r3bad,r3ad,r3in)
json.dump(out, open(OUT/'stats.json','w'), indent=1)
keys=['c4_v1_v2','c4_v1_v2pkst','c4_v2_v2pkst','c4_all_v1_v2','c4b_r3e_invoice','c4b_r3e_all','g0_plan_vs_none','g0_planonly_vs_none','g0_lessons_vs_none','g0_final_vs_base','textedit_v3_vs_fill','textedit_v4_vs_fill','textedit_v4_vs_v3','e1_A3_vs_A0','e1_A4_vs_A0','e1_A3_vs_A4','e1_A3_vs_A0_held','r3_in','r3_held','r3_web','r3e_in','r3e_held','r3d_in','r3d_held']
for k in keys: print(k, json.dumps(out[k]))
print('BASE', json.dumps({k:out[k] for k in ['e1_base','r3_base','r3_adapter','r3e_base','g0_final_families']}))
print('C4PREFS', json.dumps(out['c4_prefs']))
print('C4BPREFS', json.dumps(out['c4b_prefs']))
print('TE', json.dumps({k:out[k] for k in ['textedit_fill','textedit_v3','textedit_v4']}))
