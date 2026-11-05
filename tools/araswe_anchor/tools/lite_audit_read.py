import csv,os,random
def load(p): return {r['instance_id']:r for r in csv.DictReader(open(p))}
def hit(r,m): return r[m] not in('','None') and 0<int(float(r[m]))<=3
c=os.path.expanduser("~/araswe/lite/pysnaps"); c2=os.path.expanduser("~/araswe/cache/pysnaps")
def size(base,i): return sum(len([f for f in fs if f.endswith('.py')]) for _,_,fs in os.walk(os.path.join(base,i)))
names=["no_prose","prose_only","ar_latin","no_inline","no_ident","no_block","no_url"]
en=load("runs/lite/en/en_per_task.csv")
sz={i:size(c,i) for i in en}
enc=load("runs/expA_en/en_per_task.csv"); szc={i:size(c2,i) for i in enc}
tiers=[("<100",0,100),("100-300",100,300),(">300",300,10**7)]
def row(lbl,E,V,S,m):
    out=[]
    for t,lo,hi in [("all",0,10**7)]+tiers:
        ids=[i for i in E if lo<=S[i]<hi and i in V]
        if not ids: out.append(f"{t}: -"); continue
        out.append(f"{t} n={len(ids)} {100*sum(hit(V[i],m) for i in ids)/len(ids):.0f}")
    print(f"{lbl:12s}"," | ".join(out))
for m in("findfile_nolist","anchor","bm25"):
    print("== LITE",m)
    row("en",en,en,sz,m)
    for n in names:
        p=f"runs/lite_audit/{n}/{n}_per_task.csv"
        if os.path.exists(p): row(n,en,load(p),sz,m)
        else: print("missing",n)
print("== COMP findfile")
row("en",enc,enc,szc,"findfile_nolist")
for n in("no_prose","prose_only","ar_latin"):
    p=f"runs/audit/{n}/{n}_per_task.csv"
    if os.path.exists(p): row(n,enc,load(p),szc,"findfile_nolist")
