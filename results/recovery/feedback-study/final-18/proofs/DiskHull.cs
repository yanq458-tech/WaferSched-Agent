using System.IO.MemoryMappedFiles;
using System.Security.Cryptography;
using System.Text;
// Integer difference-bound reachability for one frozen routing and repair tick.
// stdin: n,m,P,L,d,q,failed; then routed jobs: chamber,processing,ready,due,residence,hold,initialTravel.
using System;
using System.IO;
using System.Linq;
using System.Diagnostics;
using System.Collections.Generic;
unsafe class ZoneSearch {
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


 static int[] rzone,finalOcc,seqSuffix,expected,availableStart;
 static int goalK,endMax;
 static int[] merge=new int[100];static bool Join(int[] z){
  if(!occ.SequenceEqual(finalOcc))return false;
  for(int i=0;i<81;i++)merge[i]=i%10==0?0:INF;
  for(int i=0;i<5;i++)for(int j=0;j<5;j++){merge[9*i+j]=Math.Min(merge[9*i+j],z[5*i+j]);
   int x=i==0?0:4+i,y=j==0?0:4+j;merge[9*x+y]=Math.Min(merge[9*x+y],rzone[5*j+i]);}
  merge[9+5]=S;
  for(int c=0;c<3;c++)if(occ[c]>=0){int i=occ[c],v=c+2;merge[9*v+4+v]=-(P+d+L+proc[i]);merge[9*(4+v)+v]=d+L+proc[i]+res[i];}
  for(int k=0;k<9;k++)for(int i=0;i<9;i++){int a=merge[i*9+k];if(a>=INF)continue;
   for(int j=0;j<9;j++){int b=merge[k*9+j];if(b<INF && a+b<merge[i*9+j])merge[i*9+j]=a+b;}
   if(merge[9*i+i]<0)return false;}
  return true;
 }
 static bool Prep(string list,int horizon,int[] targets){
  seqSuffix=list=="-"?new int[0]:list.Split(',').Select(int.Parse).ToArray();int[] z=new int[25];
  for(int i=0;i<M;i++)for(int j=0;j<M;j++)z[5*i+j]=i==j?0:INF;z[T*M]=-horizon;z[T]=horizon;
  finalOcc=Enumerable.Repeat(-1,3).ToArray();int mask=(1<<n)-1;
  for(int k=0;k<seqSuffix.Length;k++){int a=seqSuffix[k],i=a/2,c=chamber[i],v=2+c;Wait(z);
   if((a&1)==0){
    if(finalOcc[c]!=-1 || (mask&(1<<i))==0 || (targets[c]>=0 && (mask&(1<<targets[c]))!=0 && i!=targets[c]))return false;
    if(!Tight(z,0,T,latestV[i]+d+L+proc[i]+res[i])||!Tight(z,T,0,-releaseV[i]-P-d-L-proc[i]))return false;
    CopyClock(z,v);Shift(z);finalOcc[c]=i;mask^=1<<i;
   }else{
    if(finalOcc[c]!=i || !Tight(z,v,T,-(P+d+L+proc[i])) || !Tight(z,T,v,d+L+proc[i]+res[i]) || !Tight(z,0,T,latestV[i])||!Tight(z,T,0,-releaseV[i]))return false;
    Forget(z,v);Shift(z);Wait(z);if(!Tight(z,0,T,-(S-due[i]+P)))return false;finalOcc[c]=-1;
   }
  }
  rzone=z;endMax=S+z[T];int allowed=mask;
  expected=new int[3];availableStart=new int[]{INF,INF,INF};
  for(int c=0;c<3;c++){int i=finalOcc[c];if(i>=0){allowed|=1<<i;availableStart[c]=Math.Min(endMax-S,z[c+2]-(P+d+L+proc[i]));}}
  // Suffix may already contain the prescribed last on a chamber. Only enforce it
  // locally if still pending. A bridging wafer always has to be the final input.
  for(int c=0;c<3;c++){
   int masked=0;for(int i=0;i<n;i++)if(chamber[i]==c && (allowed&(1<<i))!=0)masked|=bit[i];
   expected[c]=masked;
   if(finalOcc[c]>=0)tail[c]=finalOcc[c];else if(tail[c]>=0 && (allowed&(1<<tail[c]))==0)tail[c]=-1;
  }
  goalK=2*n-seqSuffix.Length;startMask=allowed;
  return true;
 }
 static int startMask;
 static bool Window(int k,int mask,int[] z){
  int moves=goalK-k;int horizon=endMax;if(!Tight(z,T,0,horizon-S*moves))return false;
  int room=horizon+z[T]-moves*S; // T earliest = -z[0,T]
  for(int c=0;c<3;c++){
   int target=finalOcc[c],id=occ[c],tailBit=target<0?0:bit[target];
   int rem=remaining[c];bool mustLoad=(tailBit&rem)!=0;
   int nrem=jobCounts[c][rem],nops=2*nrem+(id<0?0:1)-(target>=0?1:0);
   int whole=rem^(mustLoad?tailBit:0);int[] ds=Debt(c,whole,0);if(ds[moves-nops]>room)return false;
   int workload=jobCounts[c][whole]*2*S+ds[0];
   int D=mustLoad?Math.Min(availableStart[c],due[target]-P):horizon;
   if(id>=0 && id!=target){
    if(!Tight(z,T,0,D-S-workload) || !Tight(z,2+c,0,D-S-workload-P-d-L-proc[id]))return false;
   }else if(!Tight(z,T,0,D-workload))return false;
   if(mustLoad && c==F && whole!=0 && q-P-d+workload>D)return false;
   if(target>=0 && id==target && !Tight(z,2+c,0,availableStart[c]))return false;
  }return true;
 }

 static bool Explore(int k,int mask){
  if((++nodes&1023)==0 && watch.Elapsed.TotalSeconds>=seconds){timeout=true;return false;}
  if(k==goalK){if(Join(layers[k])){answer=steps.Take(k).Concat(seqSuffix.Reverse().Select(a=>a^1)).ToArray();return true;}return false;}
  int[] z=layers[k];Wait(z);int pending=0,left=0,maxDeadline=-1;
  for(int c=0;c<m;c++){int id=occ[c],deadline=latest[c][remaining[c]];
   if(id>=0){
    pending++;
    if(!Tight(z,T,2+c,L+d+proc[id]+res[id]))return false;
    if(id!=finalOcc[c] && deadline<INF && (!Tight(z,T,0,deadline-S)||!Tight(z,2+c,0,deadline-S-P-d-L-proc[id])))return false;
   }else if(deadline<INF && !Tight(z,T,0,deadline))return false;
  }
  for(int i=0;i<n;i++)if((mask&(1<<i))!=0){left++;maxDeadline=Math.Max(maxDeadline,loadDue[i]);}
  if(left>0){int compulsory=left-1+Math.Max(0,pending+left-m);
   if(!Tight(z,T,0,maxDeadline-compulsory*S))return false;}
  ulong key=(uint)mask;for(int c=0;c<m;c++)key=(key<<5)|(uint)(occ[c]+1);
  if(!Window(k,mask,z))return false;if(Covered(z,key))return false;
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
  for(int c=0;c<m;c++){int i=occ[c];if(i<0 || i==finalOcc[c])continue;
   Array.Copy(z,w,M*M);Wait(w);
   if(!Tight(w,2+c,T,-(P+d+L+proc[i]))||!Tight(w,T,2+c,L+d+proc[i]+res[i]))continue;
   if(reverse && (!Tight(w,0,T,-(-latestV[i]))||!Tight(w,T,0,-releaseV[i])))continue;
   Forget(w,2+c);Shift(w);
   if(reverse){Wait(w);if(!Tight(w,0,T,-(S-(due[i]-P))))continue;}
   occ[c]=-1;steps[k]=2*i+1;
   if(Explore(k+1,mask))return true;occ[c]=i;if(timeout)return false;
  }return false;
 }

 // Each active chamber clock denotes its future outbound start. Keeping that
 // time makes the active wafer identity unnecessary once its lag window is set.
 static int[] offset, nlocal, packedJob, wmove=new int[3], residual=new int[3], idleMask=new int[3];
 static int capProof, maxStates, maxSeen;
 static int[] zr=new int[25];
 static bool Admissible(int[] z,int k,int mask,int occupied){
  int total=0, left=0, maxDue=-INF;
  for(int c=0;c<3;c++){int subset=(mask>>offset[c])&initMasks[c];remaining[c]=subset;left+=jobCounts[c][subset];
   int ac=(occupied>>c)&1;int b=finalOcc[c];bool finishedBridge=b>=0 && (subset&bit[b])==0;
   if(ac!=0 && !Tight(z,T,2+c,0))return false;
   if(finishedBridge && (ac==0 || subset!=0))return false;
   int latestLoad=latest[c][subset];if(subset!=0){
    maxDue=Math.Max(maxDue,latestAny[c][subset]);if(!Tight(z,T,0,latestLoad-ac*S))return false;
    if(ac!=0 && !Tight(z,2+c,0,latestLoad-S))return false;
   }
   bool needsBridge=b>=0&&!finishedBridge;int whole=needsBridge?subset^bit[b]:subset;
   int moves=2*jobCounts[c][whole]+(finishedBridge?0:ac)+(needsBridge?1:0);wmove[c]=moves;total+=moves;
   int until=needsBridge?Math.Min(availableStart[c],due[b]-P):endMax;
   int startLimit=until-2*S*jobCounts[c][whole]-Debt(c,whole,0)[0];
   if(!Tight(z,T,0,startLimit-((ac!=0&&!finishedBridge)?S:0)))return false;
   if(ac!=0&&!finishedBridge&&!Tight(z,2+c,0,startLimit-S))return false;
   idleMask[c]=whole;residual[c]=(ac!=0&&!finishedBridge)?Math.Max(0,-z[T*M+2+c]):0;
  }
  if(total!=goalK-k)throw new Exception("rank conservation");
  if(!Tight(z,T,0,endMax-S*total))return false;
  for(int c=0;c<3;c++){
   int free=total-wmove[c],debt0=residual[c],best=INF;var ds=Debt(c,idleMask[c],0);
   for(int v=0;v<=Math.Min(free,(debt0+S-1)/S);v++)best=Math.Min(best,Math.Max(0,debt0-v*S)+ds[free-v]);
   if(!Tight(z,T,0,endMax-S*total-best))return false;
  }
  if(left>0){
   int occN=(occupied&1)+((occupied>>1)&1)+((occupied>>2)&1);
   if(!Tight(z,T,0,maxDue-S*(left-1+Math.Max(0,left+occN-3))))return false;
  }
  if(remaining[F]==initMasks[F] && remaining[F]!=0 && !Tight(z,T,0,capProof-P-d))return false;
  return true;
 }
 static void AddZone(Dictionary<int,int[]> table,int key,int[] z){int[] a;
  if(!table.TryGetValue(key,out a))table.Add(key,(int[])z.Clone());
  else for(int j=0;j<25;j++)a[j]=Math.Max(a[j],z[j]);
 }
 static bool Finish(int[] z,int occMask){
  int wanted=0;for(int c=0;c<3;c++)if(finalOcc[c]>=0)wanted|=1<<c;
  if(occMask!=wanted)return false;
  for(int k=0;k<81;k++)merge[k]=k%10==0?0:INF;
  for(int x=0;x<5;x++)for(int y=0;y<5;y++){merge[x*9+y]=Math.Min(merge[x*9+y],z[5*x+y]);
   int a=x==0?0:4+x,b=y==0?0:4+y;merge[a*9+b]=Math.Min(merge[a*9+b],rzone[5*y+x]);}
  merge[9+5]=S;
  for(int c=0;c<3;c++)if(finalOcc[c]>=0){int a=c+2,b=4+a;merge[a*9+b]=merge[b*9+a]=0;}
  for(int k=0;k<9;k++)for(int i=0;i<9;i++){int a=merge[9*i+k];if(a==INF)continue;
   for(int j=0;j<9;j++){int b=merge[9*k+j];if(b!=INF && a+b<merge[9*i+j])merge[9*i+j]=a+b;}
   if(merge[9*i+i]<0)return false;}return true;
 }
 static void CopyFrom(int[] z,int from,int to){for(int j=0;j<5;j++)if(j!=to){z[to*5+j]=z[from*5+j];z[j*5+to]=z[j*5+from];}z[to*5+to]=0;}

 static MemoryMappedFile mm;static MemoryMappedViewAccessor view;static byte* ptr;static string rawText;
 static void OpenIndex(string path){
  long size=4096L + (1L<<(n+3))*16L;
  mm=MemoryMappedFile.CreateFromFile(path,FileMode.CreateNew,null,size,MemoryMappedFileAccess.ReadWrite);
  view=mm.CreateViewAccessor(0,size,MemoryMappedFileAccess.ReadWrite);view.SafeMemoryMappedViewHandle.AcquirePointer(ref ptr);
  view.Write(0,0x57484C32);view.Write(4,n);view.Write(8,q);view.Write(12,-1);
  int[] signature=rawText.Split((char[])null,StringSplitOptions.RemoveEmptyEntries).Select(int.Parse).ToArray();signature[5]=0;
  var digest=SHA256.Create().ComputeHash(Encoding.ASCII.GetBytes(string.Join(" ",signature)));
  view.WriteArray(64,digest,0,digest.Length);
 }
 static int CodeLo(int val,int nominal){return 1+Math.Min(254,Math.Max(0,val-nominal));}
 static int CodeHi(int val,int nominal){return val==INF||val-nominal>254?255:Math.Max(0,val-nominal);}
 static int CodeDiff(int val){return val>127?255:Math.Max(0,val+127);}
 static void StoreZone(int k,int key,int[] z){
  byte* b=ptr+4096L+16L*key;int nominal=k*S;b[0]=(byte)CodeLo(-z[T],nominal);
  int ac=key&7;
  for(int c=0;c<3;c++)if((ac&(1<<c))!=0){
   int x=2+c;b[1+c]=(byte)CodeLo(-z[x],nominal);b[4+c]=(byte)CodeHi(z[5*x+T],0);b[7+c]=(byte)CodeHi(z[5*x],nominal);
  }
  int j=10;for(int c=0;c<3;c++)for(int e=0;e<3;e++)if(e!=c){b[j++]=(byte)CodeDiff(z[(2+c)*5+2+e]);}
 }

 static bool Hull(){
  nlocal=new int[3];offset=new int[3];packedJob=new int[n];int sum=0,root=0;
  for(int c=0;c<3;c++){offset[c]=sum;nlocal[c]=Enumerable.Range(0,n).Count(i=>chamber[i]==c);sum+=nlocal[c];root|=expected[c]<<offset[c];}
  for(int i=0;i<n;i++)packedJob[i]=bit[i]<<offset[chamber[i]];
  view.WriteArray(144,packedJob,0,n);var cur=new Dictionary<int,int[]>();cur[root<<3]=(int[])layers[0].Clone();
  for(int k=0;k<=goalK;k++){
   if(cur.Count==0){view.Write(12,goalK);return false;}var next=new Dictionary<int,int[]>();maxSeen=Math.Max(cur.Count,maxSeen);
   foreach(var kv in cur){
    if((++nodes&1023)==0 && (watch.Elapsed.TotalSeconds>=seconds || next.Count>maxStates)){timeout=true;return false;}
    int key=kv.Key,mask=key>>3,ac=key&7;int[] z=kv.Value;
    if(!Admissible(z,k,mask,ac))continue;
    StoreZone(k,key,z);if(k==goalK)continue;
    for(int i=0;i<n;i++){
     int c=chamber[i],b=packedJob[i];if((mask&b)==0 || (ac&(1<<c))!=0 || !AllowedLast(c,i))continue;
     Array.Copy(z,zr,25);if(!Tight(zr,T,0,due[i]-P))continue;Wait(zr);
     if(!Tight(zr,0,T,-releaseV[i])||!Tight(zr,T,0,latestV[i]))continue;
     if(c==F && remaining[F]==initMasks[F]&&!Tight(zr,T,0,capProof-P-d))continue;
     int v=c+2;CopyClock(zr,v);int lo=P+d+L+proc[i],hi=d+L+proc[i]+res[i];
     for(int j=0;j<5;j++)if(j!=v){if(zr[5*v+j]!=INF)zr[5*v+j]+=hi;if(zr[5*j+v]!=INF)zr[5*j+v]-=lo;}
     Shift(zr);AddZone(next,((mask^b)<<3)|(ac|(1<<c)),zr);
    }
    for(int c=0;c<3;c++)if((ac&(1<<c))!=0){
     int t=finalOcc[c];if(t>=0 && (mask&packedJob[t])==0)continue;
     Array.Copy(z,zr,25);CopyFrom(zr,2+c,T);Forget(zr,2+c);Shift(zr);AddZone(next,(mask<<3)|(ac^(1<<c)),zr);
    }
   }view.Write(12,k);Console.WriteLine(k+" "+cur.Count+" "+next.Count+" "+watch.Elapsed.TotalSeconds);cur=next;
  }return false;
 }

 static void Main(string[] args){
  rawText=Console.In.ReadToEnd();var a=rawText.Split((char[])null,StringSplitOptions.RemoveEmptyEntries).Select(int.Parse).ToArray();
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
  InitEarly();watch=Stopwatch.StartNew();if(args[1]!="forward" || args[2]!="-1,-1,-1" || args[3]!="-")throw new Exception("only global wildcard indexes may be reused");
  capProof=INF;var needs=Enumerable.Range(0,n).Where(i=>chamber[i]==F).ToArray();
  if(needs.Length>1){int total=needs.Sum(i=>2*S+proc[i]-d);capProof=needs.Max(i=>due[i]+d-total+2*S+proc[i]-d);}
  maxStates=int.Parse(args[5]);
  bool prep=Prep(args[3],horizon,(int[])tail.Clone());OpenIndex(args[6]);bool hit=prep && Hull();view.SafeMemoryMappedViewHandle.ReleasePointer();view.Flush();view.Dispose();mm.Dispose();
  Console.WriteLine((timeout?"PARTIAL":"BUILT")+" "+nodes+" "+maxSeen+" "+watch.Elapsed.TotalSeconds);
 }
}
