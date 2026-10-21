import json, thx01, collections
items=[json.loads(l) for l in open('t6.jsonl')]
a=thx01.load('doofz/THX-01'); ok=0; by=collections.defaultdict(list); c=collections.Counter()
for it in items:
    lab=it['questions']['q']['question'].split('"')[1]
    r=a.decide(it['state'],{'on':{'type':'noul','question':f'Does the task say to enable (turn on) "{lab}"?'},
                            'off':{'type':'noul','question':f'Does the task say to disable (turn off) "{lab}"?'}})['answers']
    pon,poff=r['on']['noul'],r['off']['noul']
    pred='enable' if pon>=0.5 and pon>=poff else 'disable' if poff>=0.5 else 'unchanged'
    g=it['gold']['q']; ok+=pred==g; by[it['id'].rsplit('-',1)[0]].append(pred==g); c[(g,pred)]+=1
print('T6b acc',ok/len(items),'tasks all right',sum(all(v) for v in by.values()),'/',len(by)); print(c)
