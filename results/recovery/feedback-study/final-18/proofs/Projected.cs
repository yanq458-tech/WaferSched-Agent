// Integer difference-bound reachability for one frozen routing and repair tick.
// stdin: n,m,P,L,d,q,failed; then routed jobs: chamber,processing,ready,due,residence,hold,initialTravel.
using System;
using System.IO;
using System.Linq;
using System.Diagnostics;
using System.Collections.Generic;
class ZoneSearch {
 const int INF=10000000, M=5, T=1;
 static int n,m,S,P,L,d,q,F; static int[] chamber,proc,ready,due,res,hold,first,bit,steps,answer;
 static int[][] latest; static int[] initMasks,occ;static int[][] layers;static int[] remaining;
 static long nodes,hits;static Stopwatch watch;static double seconds;
 static int[][] jobCounts, latestAny; static int[][][] debt; static int shiftThreshold;
 static int energyCuts; static bool reverse;static int[] releaseV,latestV,loadDue;static bool timeout;static int entries; static Dictionary<ulong,List<int[]>> memo=new Dictionary<ulong,List<int[]>>();
 static bool Tight(int[] z,int x,int y,int k) {
  if(z[x*M+y]<=k)return true;
  if(z[y*M+x]+k<0)return false;
  for(int a=0;a<M;a++){int ax=z[a*M+x];if(ax==INF)continue;int t=ax+k;
   for(int b=0;b<M;b++){int yb=z[y*M+b];if(yb!=INF && t+yb<z[a*M+b])z[a*M+b]=t+yb;}
  }return true;
 }
 static void Wait(int[] z){for(int j=0;j<M;j++)if(j!=T)z[T*M+j]=INF;}
 static void Shift(int[] z){for(int j=0;j<M;j++)if(j!=T){if(z[T*M+j]!=INF)z[T*M+j]+=S;if(z[j*M+T]!=INF)z[j*M+T]-=S;}}
 static void Forget(int[] z,int c){for(int j=0;j<M;j++)if(j!=c)z[c*M+j]=z[j*M+c]=INF;z[c*M+c]=0;}
 static void CopyClock(int[] z,int c){for(int j=0;j<M;j++)if(j!=c){z[c*M+j]=z[T*M+j];z[j*M+c]=z[j*M+T];}z[c*M+c]=0;}
 static bool Covered(int[] z,ulong key){
  List<int[]> states;
  if(memo.TryGetValue(key,out states)){
   for(int i=states.Count-1;i>=0;i--){int[] old=states[i];bool contained=true,contains=true;
    for(int k=0;k<M*M && (contained||contains);k++){if(z[k]>old[k])contained=false;if(z[k]<old[k])contains=false;}
    if(contained){hits++;return true;}if(contains){states.RemoveAt(i);entries--;}
   }
  }else{states=new List<int[]>();memo.Add(key,states);}
  int[] elastic=(int[])z.Clone();
  if(-z[T]>=shiftThreshold){for(int x=1;x<M;x++)elastic[x*M]=INF;}
  states.Add(elastic);entries++;
  if(entries>=1100000){memo.Clear();entries=0;}return false;
 }
 static int[] Debt(int c,int mask,int drop){
  int key=2*mask+drop;
  if(debt[c][key]!=null)return debt[c][key];
  var penalties=new List<int>();
  for(int i=0;i<n;i++)if(chamber[i]==c && (bit[i]&mask)!=0)penalties.Add(proc[i]-d);
  penalties.Sort();if(drop!=0 && penalties.Count>0)penalties.RemoveAt(penalties.Count-1);
  int total=0,full=0;var rem=new List<int>();foreach(int e in penalties){total+=e;full+=e/S;rem.Add(e%S);}
  rem.Sort((a,b)=>b.CompareTo(a));var outp=new int[2*n+1];outp[0]=total;
  for(int j=1;j<=2*n;j++){int k=j-full-1;outp[j]=outp[j-1]-(j<=full?S:k<rem.Count?rem[k]:0);}
  return debt[c][key]=outp;
 }
 static bool Enough(int[] z){
  int now=-z[T]; // D[0,T] is minus the earliest robot-free time.
  int aa=jobCounts[0][remaining[0]],bb=jobCounts[1][remaining[1]],cc=jobCounts[2][remaining[2]];
  if(aa+bb+cc<2)return true;
  int a=2*aa+(occ[0]<0?0:1),b=2*bb+(occ[1]<0?0:1),c=2*cc+(occ[2]<0?0:1);
  for(int last=0;last<3;last++){
   int deadline=latestAny[last][remaining[last]];if(deadline==int.MinValue)continue;
   // Keep as many wafers pending as possible in the two other chambers.
   // Dropping their last outbound always relaxes energy and capacity: when this
   // drops a foreign move, its missing S units offset any increased idle debt.
   int m0=last==0?a-2:Math.Max(0,a-1),m1=last==1?b-2:Math.Max(0,b-1),m2=last==2?c-2:Math.Max(0,c-1);
   int moves=m0+m1+m2,room=deadline-now-S*moves;
   if(room<0)continue;
   // In every chamber at most one not-yet-loaded job may remain unfinished at the cut.
   if(Debt(0,remaining[0],1)[moves-m0]>room || Debt(1,remaining[1],1)[moves-m1]>room || Debt(2,remaining[2],1)[moves-m2]>room)continue;
   return true;
  }
  energyCuts++;return false;
 }

 // min mandatory idle in k complete same-chamber pairs. The shortest k jobs
 // relax matching. Each foreign transfer can hide at most S consecutive ticks.
 static Dictionary<long,int[]> idleTable=new Dictionary<long,int[]>();
 static int Idle(int c,int mask,int k,int foreign){
  if(k<=0)return 0;
  long key=((long)c<<36)|((long)mask<<6)|(uint)k;int[] vals;
  if(!idleTable.TryGetValue(key,out vals)){
   var v=Enumerable.Range(0,n).Where(i=>chamber[i]==c && (bit[i]&mask)!=0).Select(i=>Math.Max(0,proc[i]-d)).OrderBy(x=>x).Take(k).ToArray();
   int total=v.Sum(),full=v.Sum(x=>x/S);var rem=v.Select(x=>x%S).OrderByDescending(x=>x).ToArray();
   vals=new int[2*n+1];vals[0]=total;for(int j=1;j<=2*n;j++){int pos=j-full-1;vals[j]=vals[j-1]-(j<=full?S:pos<rem.Length?rem[pos]:0);}
   idleTable[key]=vals;
  }return vals[foreign];
 }
 static bool Phase(int[] masks,int[] moves,int end){
  int c1=(F+1)%3,c2=(F+2)%3;
  int af=moves[F],a=moves[c1],b=moves[c2],all=af+a+b,room=end-all*S;
  if(room<0)return false;
  if(Idle(F,masks[F],af/2,a+b)>room || Idle(c1,masks[c1],a/2,af+b)>room || Idle(c2,masks[c2],b/2,af+a)>room)return false;
  if(af==0)return true;
  int gate=Math.Max(0,q-P-d);
  int maxElapsedPost=end-gate;
  if(maxElapsedPost<af*S+Idle(F,masks[F],af/2,a+b))return false;
  for(int u=a;u>=0;u--){int minOther=Math.Max(0,all-u-maxElapsedPost/S);
   for(int v=b;v>=minOther;v--){
    int post=all-u-v,postRoom=maxElapsedPost-S*post;
    int idf=Idle(F,masks[F],af/2,a+b-u-v);if(idf>postRoom)continue;
    int id1=Idle(c1,masks[c1],a/2-(u+1)/2,af+b-v);if(id1>postRoom)continue;
    int id2=Idle(c2,masks[c2],b/2-(v+1)/2,af+a-u);if(id2>postRoom)continue;
    int idpost=Math.Max(idf,Math.Max(id1,id2));
    int preidle=Math.Max(Idle(c1,masks[c1],u/2,v),Idle(c2,masks[c2],v/2,u));
    if(preidle+idpost<=room)return true;
   }
  }return false;
 }
 static int[] mc=new int[3];static bool RootPossible(){
  for(int last=0;last<m;last++){
   int end=-1;for(int i=0;i<n;i++)if(chamber[i]==last)end=Math.Max(end,due[i]-P);if(end<0)continue;
   for(int c=0;c<m;c++)mc[c]=Math.Max(0,2*jobCounts[c][initMasks[c]]-(last==c?2:1));
   if(Phase(initMasks,mc,end))return true;
  }return false;
 }
 static bool ReversePrefix(int[] z){
  for(int c=0;c<m;c++)mc[c]=2*jobCounts[c][remaining[c]]+(occ[c]<0?0:1);
  return Phase(remaining,mc,z[0*M+T]*0+z[0*M+T]+S); // z[0,T] bounds -T, i.e. the latest original time.
 }


 static int[][] early;static int[] twin;
 static void InitEarly(){
  early=new int[3][];for(int c=0;c<3;c++){early[c]=new int[initMasks[c]+1];
   for(int mask=1;mask<=initMasks[c];mask++){int best=INF;
    for(int i=0;i<n;i++)if(chamber[i]==c && (mask&bit[i])!=0){
     int start=Math.Max(early[c][mask^bit[i]],Math.Max(ready[i],first[i]));
     int v=Math.Max(start,releaseV[i]);
     if(start<=due[i]-P && v<=latestV[i])best=Math.Min(best,v+P+d+L+proc[i]+S);
    }early[c][mask]=best;
   }
  }
 }
 static bool Prefix(int[] z,int depth){
  for(int c=0;c<3;c++){int e=early[c][remaining[c]],i=occ[c];if(e==INF)return false;
   if(i>=0){if(e>due[i]-P || !Tight(z,2+c,0,-(Math.Max(e,releaseV[i])+P+d+L+proc[i])) || !Tight(z,T,0,-Math.Max(e,releaseV[i])))return false;}
   else if(remaining[c]!=0 && !Tight(z,T,0,S-e))return false;
  }
  if(!ReversePrefix(z))return false;
  if(depth>14)return true;
  // All forward sources represented by this cut must still be picked on time.
  for(int last=0;last<3;last++){
   if(remaining[last]==0 && occ[last]<0)continue;
   int end=-1;for(int i=0;i<n;i++)if(chamber[i]==last && (occ[last]==i || (occ[last]<0 && (bit[i]&remaining[last])!=0)))end=Math.Max(end,due[i]-P);
   end=Math.Min(end,z[T]);if(occ[last]>=0){int i=occ[last];end=Math.Min(end,z[2+last]-P-d-L-proc[i]);}
   for(int c=0;c<3;c++){int count=jobCounts[c][remaining[c]]+(occ[c]>=0?1:0);mc[c]=Math.Max(0,2*count-(c==last?2:1));}
   if(Phase(remaining,mc,end))return true;
  }
  return false;
 }
 static void Coarsen(int width){
  twin=new int[n];
  for(int i=0;i<n;i++){twin[i]=-1;if(width<=0)continue;
   for(int j=0;j<i;j++)if(chamber[i]==chamber[j] && proc[i]/width==proc[j]/width){
    twin[i]=j;break;
   }}
  if(width<=0)return;
  var groups=Enumerable.Range(0,n).GroupBy(i=>chamber[i]+100*(proc[i]/width)).Select(g=>g.ToArray()).ToArray();
  foreach(var ids in groups){
   int pr=ids.Min(i=>proc[i]),end=ids.Max(i=>res[i]+proc[i]),reld=ids.Min(i=>ready[i]),fi=ids.Min(i=>first[i]),du=ids.Max(i=>due[i]),held=ids.Max(i=>due[i]+hold[i])-du;
   foreach(int i in ids){proc[i]=pr;res[i]=end-pr;ready[i]=reld;first[i]=fi;due[i]=du;hold[i]=held;}
   for(int k=1;k<ids.Length;k++)twin[ids[k]]=ids[k-1];
  }
 }


 static int[] tail=new int[3];static int[] fixedMasks=new int[3],orderTail=new int[3];static bool KnownLast(){
  // Test every possible order of the last original source pickup in the three chambers.
  // Before that pickup keep the mandatory input/output pairs of preceding chambers.
  for(int a=0;a<3;a++)for(int b=0;b<3;b++)if(a!=b){orderTail[0]=a;orderTail[1]=b;orderTail[2]=3-a-b;bool ok=true;
   int prev=-S;
   for(int k=0;k<3 && ok;k++){
    int last=orderTail[k],id=tail[last];if(initMasks[last]==0)continue;
    int deadline=-1,earliest=INF;
    for(int i=0;i<n;i++)if(chamber[i]==last && (id<0 || id==i)){
     deadline=Math.Max(deadline,due[i]-P);earliest=Math.Min(earliest,early[last][initMasks[last]^bit[i]]);}
    prev=Math.Max(earliest,prev+S);if(prev>deadline){ok=false;break;}
    Array.Clear(mc,0,3);Array.Clear(fixedMasks,0,3);
    for(int h=0;h<=k;h++){int c=orderTail[h];mc[c]=Math.Max(0,2*jobCounts[c][initMasks[c]]-(c==last?2:1));fixedMasks[c]=initMasks[c]^(tail[c]<0?0:bit[tail[c]]);}
    if(!Phase(fixedMasks,mc,deadline))ok=false;
   }if(ok)return true;
  }return false;
 }
 static bool AllowedLast(int c,int i){if(tail[c]<0)return true;
  if(reverse)return remaining[c]!=initMasks[c] || i==tail[c];
  return i!=tail[c] || remaining[c]==bit[i];}


 // Project the old chamber identity and its loading clock onto the already
 // permitted time of its unique future removal. Minkowski addition of each
 // independent [min,max] age interval gives these DBM entries by elimination.
 // Future unstarted jobs depend on the occupied chamber, not the old wafer ID.
 static int[] proj=new int[M*M],lowerShift=new int[M],upperShift=new int[M];
 static bool Projected(int[] old,int mask){
  ulong key=(uint)mask;
  for(int c=0;c<m;c++){int i=occ[c],h=2+c;int label=i<0?0:1;
   if(i>=0 && reverse && -old[T]<-(due[i]-P))label=2+i;
   key=(key<<5)|(uint)label;
   lowerShift[h]=i<0?0:P+d+L+proc[i];upperShift[h]=i<0?0:d+L+proc[i]+res[i];
  }
  for(int x=0;x<M;x++)for(int y=0;y<M;y++){int k=x*M+y,v=old[k];proj[k]=x==y?0:v==INF?INF:v+upperShift[x]-lowerShift[y];}
  if(reverse)for(int c=0;c<m;c++){int i=occ[c];if(i>=0 && (!Tight(proj,0,2+c,latestV[i]) || !Tight(proj,2+c,0,-releaseV[i])))return true;}
  return Covered(proj,key);
 }

 static bool Explore(int k,int mask){
  if((++nodes&1023)==0 && watch.Elapsed.TotalSeconds>=seconds){timeout=true;return false;}
  if(k==2*n){answer=(int[])steps.Clone();return true;}
  int[] z=layers[k];Wait(z);int pending=0,left=0,maxDeadline=-1;
  for(int c=0;c<m;c++){int id=occ[c],deadline=latest[c][remaining[c]];
   if(id>=0){
    pending++;
    if(!Tight(z,T,2+c,L+d+proc[id]+res[id]))return false;
    if(deadline<INF && (!Tight(z,T,0,deadline-S)||!Tight(z,2+c,0,deadline-S-P-d-L-proc[id])))return false;
   }else if(deadline<INF && !Tight(z,T,0,deadline))return false;
  }
  for(int i=0;i<n;i++)if((mask&(1<<i))!=0){left++;maxDeadline=Math.Max(maxDeadline,loadDue[i]);}
  if(left>0){int compulsory=left-1+Math.Max(0,pending+left-m);
   if(!Tight(z,T,0,maxDeadline-compulsory*S))return false;}
  ulong key=(uint)mask;for(int c=0;c<m;c++)key=(key<<5)|(uint)(occ[c]+1);
  if(!Enough(z))return false;if(reverse && k>0 && k<2*n-2 && !Prefix(z,k))return false;if(Projected(z,mask))return false;
  int[] w=layers[k+1];
  // Try transfers into empty chambers, then outbound transfers. Both orders are exhaustive.
  for(int i=0;i<n;i++)if((mask&(1<<i))!=0 && occ[chamber[i]]<0 && AllowedLast(chamber[i],i) && (twin[i]<0 || (mask&(1<<twin[i]))==0)){
   int c=chamber[i];Array.Copy(z,w,M*M);
   if(!reverse && !Tight(w,T,0,due[i]-P))continue;
   Wait(w);
   int release=reverse ? -(latestV[i]+L+d+proc[i]+res[i]) : releaseV[i];
   if(!Tight(w,0,T,-release)||!Tight(w,T,0,reverse ? loadDue[i] : latestV[i]))continue;
   CopyClock(w,2+c);Shift(w);occ[c]=i;remaining[c]^=bit[i];steps[k]=2*i;
   if(Explore(k+1,mask^(1<<i)))return true;
   occ[c]=-1;remaining[c]^=bit[i];if(timeout)return false;
  }
  for(int c=0;c<m;c++){int i=occ[c];if(i<0)continue;
   Array.Copy(z,w,M*M);Wait(w);
   if(!Tight(w,2+c,T,-(P+d+L+proc[i]))||!Tight(w,T,2+c,L+d+proc[i]+res[i]))continue;
   if(reverse && (!Tight(w,0,T,-(-latestV[i]))||!Tight(w,T,0,-releaseV[i])))continue;
   Forget(w,2+c);Shift(w);
   if(reverse){Wait(w);if(!Tight(w,0,T,-(S-(due[i]-P))))continue;}
   occ[c]=-1;steps[k]=2*i+1;
   if(Explore(k+1,mask))return true;occ[c]=i;if(timeout)return false;
  }return false;
 }
 static void Main(string[] args){
  var a=Console.In.ReadToEnd().Split((char[])null,StringSplitOptions.RemoveEmptyEntries).Select(int.Parse).ToArray();
  int j=0;n=a[j++];m=a[j++];P=a[j++];L=a[j++];d=a[j++];q=a[j++];F=a[j++];S=P+2*d+L;
  if(m!=3 || n>25)throw new Exception("Domain");
  reverse=args.Length>1 && args[1]=="reverse";seconds=double.Parse(args[0],System.Globalization.CultureInfo.InvariantCulture);
  chamber=new int[n];proc=new int[n];ready=new int[n];due=new int[n];res=new int[n];hold=new int[n];first=new int[n];bit=new int[n];steps=new int[2*n];
  for(int i=0;i<n;i++){chamber[i]=a[j++];proc[i]=a[j++];ready[i]=a[j++];due[i]=a[j++];res[i]=a[j++];hold[i]=a[j++];first[i]=a[j++];}
  tail=args[2].Split(',').Select(int.Parse).ToArray();Coarsen(0);releaseV=new int[n];latestV=new int[n];loadDue=new int[n];int horizon=0;
  for(int i=0;i<n;i++){
   releaseV[i]=Math.Max(Math.Max(0,Math.Max(first[i],ready[i])),chamber[i]==F?q-P-d:0);
   latestV[i]=due[i]-P+hold[i]-d-L;
   loadDue[i]=reverse ? -releaseV[i]-P-d-L-proc[i] : due[i]-P;
   horizon=Math.Max(horizon,latestV[i]+L+d+proc[i]+res[i]);}
  latest=new int[m][];initMasks=new int[m];occ=Enumerable.Repeat(-1,m).ToArray();
  for(int c=0;c<m;c++){
   var ids=Enumerable.Range(0,n).Where(i=>chamber[i]==c).OrderBy(i=>(i==tail[c] && !reverse)?INF:loadDue[i]+2*S+proc[i]-d).ToArray();
   latest[c]=new int[1<<ids.Length];latest[c][0]=INF;initMasks[c]=latest[c].Length-1;
   for(int k=0;k<ids.Length;k++){int i=ids[k];bit[i]=1<<k;}
   for(int b=1;b<latest[c].Length;b++){int k=0;while((b&(1<<k))==0)k++;int i=ids[k],next=b^(1<<k);
    latest[c][b]=Math.Min(loadDue[i],latest[c][next]-(2*S+proc[i]-d));}
  }
  shiftThreshold=reverse?Enumerable.Range(0,n).Max(i=>Math.Max(S-due[i]+P,-latestV[i])):releaseV.Max();
  jobCounts=new int[m][];latestAny=new int[m][];debt=new int[m][][];
  for(int c=0;c<m;c++){int len=initMasks[c]+1;jobCounts[c]=new int[len];latestAny[c]=new int[len];latestAny[c][0]=int.MinValue;
   debt[c]=new int[2*len][];for(int i=0;i<n;i++)if(chamber[i]==c)for(int mask=bit[i];mask<len;mask++)if((mask&bit[i])!=0){
    jobCounts[c][mask]++;latestAny[c][mask]=jobCounts[c][mask]==1?loadDue[i]:Math.Max(latestAny[c][mask],loadDue[i]);}}
  remaining=(int[])initMasks.Clone();layers=new int[2*n+1][];for(int k=0;k<layers.Length;k++)layers[k]=new int[M*M];
  var z=layers[0];for(int a1=0;a1<M;a1++)for(int b=0;b<M;b++)z[a1*M+b]=a1==b?0:INF;z[T*M]=reverse?-horizon:0;z[T]=-z[T*M];
  InitEarly();watch=Stopwatch.StartNew();bool hit=KnownLast() && RootPossible() && Explore(0,(1<<n)-1);
  Console.WriteLine((hit?"FEASIBLE":timeout?"UNKNOWN":"INFEASIBLE")+" "+nodes+" "+hits+" "+watch.Elapsed.TotalSeconds.ToString(System.Globalization.CultureInfo.InvariantCulture));
  if(hit)Console.WriteLine(string.Join(" ",reverse?answer.Reverse().Select(x=>x^1):answer.AsEnumerable()));
 }
}
