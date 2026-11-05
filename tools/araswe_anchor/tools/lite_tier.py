import csv,os,random
def load(p): return {r['instance_id']:r for r in csv.DictReader(open(p))}
def hit(r,m): return r[m] not in('','None') and 0<int(float(r[m]))<=3
L=["ar","hi","zh","ru","es","fr"]
sets=[("COMP","runs/expA_en/en_per_task.csv","runs/expA_%s_mix/%s_mix_per_task.csv","~/araswe/cache/pysnaps"),
      ("LITE","runs/lite/en/en_per_task.csv","runs/lite/%s_mix/%s_mix_per_task.csv","~/araswe/lite/pysnaps")]
rows=[]
for name,b,t,c in sets:
    en=load(b); V={l:load(t%(l,l)) for l in L}; c=os.path.expanduser(c)
    for i,r in en.items():
        n=sum(len([f for f in fs if f.endswith('.py')]) for _,_,fs in os.walk(os.path.join(c,i)))
        d={m:[int(hit(V[l][i],m))-int(hit(r,m)) for l in L] for m in("findfile_nolist","bm25")}
        rows.append((name,r['repo'],n,int(hit(r,"findfile_nolist")),d))
def boot(v):
    random.seed(42);n=len(v);s=[]
    for _ in range(4000):
        s.append(sum(random.choice(v) for _ in range(n))/n)
    s.sort();return s[100],s[3899]
tiers=[(0,100),(100,300),(300,10**6)]
for m in("findfile_nolist","bm25"):
    print("==",m,"mean change in top-3 pts over 6 languages")
    for name in("COMP","LITE","BOTH"):
        for lo,hi in tiers:
            x=[r for r in rows if (name=="BOTH" or r[0]==name) and lo<=r[2]<hi]
            if not x: continue
            v=[100*sum(r[4][m])/6 for r in x]
            a,b=boot(v)
            bl=" ".join(f"{sum(r[4][m][k] for r in x)*100/len(x):+5.1f}" for k in range(6))
            print(f"{name} files {lo}-{hi}: n={len(x):3d} EN {100*sum(r[3] for r in x)/len(x):3.0f} mean {sum(v)/len(v):+5.1f} [{a:+.1f},{b:+.1f}]  {bl}")
print("LITE without psf/requests, findfile:")
x=[r for r in rows if r[0]=="LITE" and r[1]!="psf/requests"]
print(len(x)," ".join(f"{L[k]} {sum(r[4]['findfile_nolist'][k] for r in x)*100/len(x):+.1f}" for k in range(6)))
