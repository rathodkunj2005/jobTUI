import csv, json, re, urllib.request, datetime
from pathlib import Path
import job_fetcher
KNOWN = job_fetcher._KNOWN
p=Path('data/applications.csv')
rows=[]
with p.open(newline='') as f:
    for idx,row in enumerate(csv.DictReader(f),1):
        if row.get('Status') in {'Not Applied','Watching','Referral Pending'}:
            rows.append((idx,row))

def map_company(name):
    n=name.lower()
    for k,v in sorted(KNOWN.items(), key=lambda kv: -len(kv[0])):
        if k in n:
            return v,k
    return None,None

def urlopen_json(url, timeout=20):
    req=urllib.request.Request(url, headers={'User-Agent':'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)

def clean(s): return re.sub('<[^>]+>',' ', s or '').replace('&nbsp;',' ')
include=re.compile(r'\b(software|backend|back-end|infrastructure|infra|platform|machine learning|\bML\b|\bAI\b|data|distributed|devtools|developer|systems|site reliability|SRE|cloud|database|engineer|engineering)\b', re.I)
exclude=re.compile(r'\b(intern|internship|co-?op|apprentice|manager|director|sales engineer|support engineer|customer|solutions engineer|hardware|mechanical|electrical)\b', re.I)

def is_candidate_title(title):
    return bool(include.search(title or '')) and not bool(exclude.search(title or ''))

def fulltime_signal_greenhouse(d):
    md=d.get('metadata') or []
    vals=[]
    for m in md:
        vals.append(f"{m.get('name')}: {m.get('value')}")
        if str(m.get('name','')).lower() in {'time type','employment type','job type'} and re.search(r'full.?time|regular|salaried|standard', str(m.get('value','')), re.I):
            return True, '; '.join(vals)
    content=clean(d.get('content') or '')
    m=re.search(r'(this full-time position|full-time employees|full time employees|full-time role|full time role)', content, re.I)
    if m: return True, m.group(1)
    return False, '; '.join(vals)[:500]

def fetch_greenhouse(company, board, priority):
    out=[]
    try:
        jobs=urlopen_json(f'https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=false') .get('jobs',[])
    except Exception as e:
        return [{'company':company,'error':f'list {e}'}]
    cand=[j for j in jobs if is_candidate_title(j.get('title',''))]
    for j in cand[:160]:
        jid=j.get('id')
        try:
            d=urlopen_json(f'https://boards-api.greenhouse.io/v1/boards/{board}/jobs/{jid}', timeout=15)
            ft, sig=fulltime_signal_greenhouse(d)
            if not ft: continue
            date=d.get('first_published') or d.get('updated_at')
            out.append({'company':company,'priority':priority,'ats':'greenhouse','board':board,'title':d.get('title') or j.get('title'), 'date':date, 'url':d.get('absolute_url') or j.get('absolute_url'), 'location':(d.get('location') or {}).get('name') or (j.get('location') or {}).get('name'), 'ft_signal':sig[:300]})
        except Exception:
            pass
    return out

def fetch_lever(company, site, priority):
    out=[]
    try:
        data=urlopen_json(f'https://api.lever.co/v0/postings/{site}?mode=json&limit=250')
    except Exception as e:
        return [{'company':company,'error':f'list {e}'}]
    for j in data:
        title=j.get('text') or ''
        if not is_candidate_title(title): continue
        cats=j.get('categories') or {}
        commitment=str(cats.get('commitment') or '')
        if not re.search(r'full.?time', commitment, re.I):
            continue
        created=j.get('createdAt')
        date=datetime.datetime.utcfromtimestamp(created/1000).isoformat()+'Z' if created else None
        out.append({'company':company,'priority':priority,'ats':'lever','board':site,'title':title,'date':date,'url':j.get('hostedUrl') or j.get('applyUrl'), 'location':cats.get('location'), 'ft_signal':commitment})
    return out

allres=[]
for priority,(idx,row) in enumerate(rows,1):
    company=row['Company']; mapping,key=map_company(company)
    if not mapping: continue
    typ, board=mapping
    if typ=='greenhouse': res=fetch_greenhouse(company, board, priority)
    elif typ=='lever': res=fetch_lever(company, board, priority)
    else: res=[]
    allres.extend(res)

def parse_date(x):
    if not x: return datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)
    s=x.replace('Z','+00:00')
    try: return datetime.datetime.fromisoformat(s)
    except Exception:
        try: return datetime.datetime.strptime(x[:10],'%Y-%m-%d').replace(tzinfo=datetime.timezone.utc)
        except: return datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)

valid=[r for r in allres if not r.get('error') and r.get('date')]
valid.sort(key=lambda r:(parse_date(r['date']), -r['priority']), reverse=True)
print('VALID_COUNT', len(valid))
for r in valid[:50]:
    print(json.dumps(r, ensure_ascii=False))
print('ERRORS sample')
for r in [x for x in allres if x.get('error')][:20]: print(json.dumps(r))
